import pytest

from tests.factory import BLUE, CLASSIC, RED, kill, match, round_result
from vstats.raw.filename import parse_filename
from vstats.raw.models import RawMatch
from vstats.reference.resolver import load_reference
from vstats.transform import MatchError, MatchRecord, transform_match

FILENAME = "UNIVAVA_G_001a_19-09-26_team_one_{a}_x_{b}_team_two_ascent.json"


def build(rounds: list[dict], red_won: int, blue_won: int, *, filename_scores: tuple[int, int] | None = None,
          observer: bool = False) -> MatchRecord:
    a, b = filename_scores or (red_won, blue_won)
    raw = RawMatch.model_validate(match(rounds, red_won, blue_won, observer=observer))
    return transform_match(raw, parse_filename(FILENAME.format(a=a, b=b)), load_reference(), "fixture.json")


def test_resolves_red_and_blue_by_score_order() -> None:
    rounds = [round_result(0, "Blue", "Defender", [])]
    direct = build(rounds, 0, 1, filename_scores=(0, 1))
    swapped = build(rounds, 0, 1, filename_scores=(1, 0))
    assert (direct.red_slug, direct.blue_slug) == ("team_one", "team_two")
    assert (swapped.red_slug, swapped.blue_slug) == ("team_two", "team_one")


def test_rejects_score_mismatch() -> None:
    with pytest.raises(MatchError):
        build([round_result(0, "Red", "Attacker", [])], 1, 0, filename_scores=(13, 5))


def test_sides_follow_winning_role() -> None:
    record = build([round_result(0, "Red", "Defender", [])], 1, 0)
    round_ = record.rounds[0]
    assert round_.winner_side == "defense"
    assert round_.defense_slug == record.red_slug
    assert {p.side for p in round_.players if p.puuid in RED} == {"defense"}
    assert {p.side for p in round_.players if p.puuid in BLUE} == {"attack"}
    assert {p.first_side for p in record.players if p.puuid in BLUE} == {"attack"}


def test_first_kill_and_trade_window() -> None:
    kills = [
        kill(10_000, BLUE[0], RED[0]),
        kill(13_000, RED[1], BLUE[0]),
        kill(30_000, BLUE[1], RED[1]),
        kill(40_000, RED[2], BLUE[1]),
    ]
    record = build([round_result(0, "Red", "Attacker", kills)], 1, 0)
    first, trade, late_death, late_kill = record.rounds[0].kills
    assert first.is_first_kill and not trade.is_first_kill
    assert trade.is_trade and first.traded_after_ms == 3_000
    assert not late_kill.is_trade and late_death.traded_after_ms is None


def test_self_and_team_kills_are_classified_and_excluded_from_kill_counts() -> None:
    kills = [
        kill(5_000, RED[0], RED[1]),
        kill(6_000, BLUE[0], BLUE[0], damage_type="Fall", item=""),
        kill(90_000, None, BLUE[1], damage_type="Bomb", item=""),
    ]
    record = build([round_result(0, "Red", "Attacker", kills, code="Detonate", planter=RED[2], plant_site="A")], 1, 0)
    team_kill, fall, bomb = record.rounds[0].kills
    assert (team_kill.kind, fall.kind, bomb.kind) == ("team", "self", "self")
    assert fall.killer is None and bomb.killer is None
    assert not any(k.is_first_kill for k in record.rounds[0].kills)
    assert {p.puuid: p.kills for p in record.rounds[0].players}[RED[0]] == 0
    assert record.rounds[0].plant_site == "A"
    assert not [i for i in record.issues if i.severity != "info"]


def test_distance_uses_killer_position_and_centimeter_units() -> None:
    record = build(
        [round_result(0, "Red", "Attacker", [kill(1_000, RED[0], BLUE[0], killer_at=(0, 0), victim_at=(300, 400))])],
        1,
        0,
    )
    assert record.rounds[0].kills[0].distance_m == 5.0


def test_round_player_economy_and_damage() -> None:
    damage = {RED[0]: [{"receiver": BLUE[0], "damage": 150, "headshots": 1, "bodyshots": 2, "legshots": 0}]}
    record = build([round_result(0, "Red", "Attacker", [kill(1_000, RED[0], BLUE[0], item=CLASSIC)], damage=damage)], 1, 0)
    stats = {p.puuid: p for p in record.rounds[0].players}
    assert stats[RED[0]].damage_dealt == 150 and stats[RED[0]].headshots == 1 and stats[RED[0]].kills == 1
    assert stats[BLUE[0]].died and not stats[RED[0]].died
    assert record.rounds[0].kills[0].weapon_uuid == CLASSIC.lower()


def test_timeout_round_and_observer_are_reported() -> None:
    rounds = [round_result(0, "Blue", "Defender", [], code="", result="Round timer expired")]
    record = build(rounds, 0, 1, observer=True)
    assert record.rounds[0].result_code == "Timeout"
    assert len(record.players) == 10
    assert {i.code for i in record.issues} == {"observer_removed", "timeout_rounds"}


def test_rejects_match_without_winner() -> None:
    rounds = [round_result(0, "Red", "Attacker", []), round_result(1, "Blue", "Attacker", [])]
    with pytest.raises(MatchError):
        build(rounds, 1, 1)


def test_every_death_of_a_multikill_is_traded_when_the_killer_dies() -> None:
    kills = [
        kill(10_000, BLUE[0], RED[0]),
        kill(11_000, BLUE[0], RED[1]),
        kill(12_000, RED[2], BLUE[0]),
    ]
    record = build([round_result(0, "Red", "Attacker", kills)], 1, 0)
    first, second, trade = record.rounds[0].kills
    assert trade.is_trade
    assert (first.traded_after_ms, second.traded_after_ms) == (2_000, 1_000)


def test_trade_in_the_same_millisecond_counts() -> None:
    kills = [kill(10_000, BLUE[0], RED[0]), kill(10_000, RED[1], BLUE[0])]
    record = build([round_result(0, "Red", "Attacker", kills)], 1, 0)
    by_victim = {k.victim: k for k in record.rounds[0].kills}
    assert by_victim[RED[0]].traded_after_ms == 0 and by_victim[BLUE[0]].is_trade
