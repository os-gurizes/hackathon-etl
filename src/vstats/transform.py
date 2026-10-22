import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from vstats.quality import Issue
from vstats.raw.filename import MatchFilename
from vstats.raw.models import Kill, RawMatch, RoundResult
from vstats.reference.resolver import Reference

Side = Literal["attack", "defense"]
KillKind = Literal["enemy", "team", "self"]

TRADE_WINDOW_MS = 5_000
UNITS_PER_METER = 100
PLAYING_TEAMS = ("Red", "Blue")


class MatchError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PositionRecord:
    puuid: str
    side: Side
    x: int
    y: int
    nx: float | None
    ny: float | None
    view_rad: float


@dataclass(slots=True)
class KillRecord:
    seq: int
    t_round_ms: int
    t_game_ms: int
    killer: str | None
    victim: str
    kind: KillKind
    damage_type: str
    weapon_uuid: str | None
    ability_slot: str | None
    is_secondary_fire: bool
    killer_xy: tuple[int, int] | None
    victim_xy: tuple[int, int]
    distance_m: float | None
    assistants: tuple[str, ...]
    positions: tuple[PositionRecord, ...]
    is_first_kill: bool = False
    is_trade: bool = False
    traded_after_ms: int | None = None


@dataclass(frozen=True, slots=True)
class DamageRecord:
    dealer: str
    receiver: str
    damage: int
    headshots: int
    bodyshots: int
    legshots: int


@dataclass(frozen=True, slots=True)
class RoundPlayerRecord:
    puuid: str
    team_slug: str
    side: Side
    score: int
    loadout_value: int
    spent: int
    remaining: int
    weapon_uuid: str | None
    armor_uuid: str | None
    damage_dealt: int
    headshots: int
    bodyshots: int
    legshots: int
    kills: int
    died: bool


@dataclass(frozen=True, slots=True)
class RoundRecord:
    number: int
    winner_slug: str
    winner_side: Side
    attack_slug: str
    defense_slug: str
    result_code: str
    ceremony: str | None
    plant_site: str | None
    plant_time_ms: int | None
    planter: str | None
    plant_xy: tuple[int, int] | None
    defuser: str | None
    defuse_time_ms: int | None
    players: tuple[RoundPlayerRecord, ...]
    kills: tuple[KillRecord, ...]
    damage: tuple[DamageRecord, ...]


@dataclass(frozen=True, slots=True)
class PlayerRecord:
    puuid: str
    game_name: str
    tag_line: str
    team_slug: str
    agent_uuid: str
    first_side: Side
    score: int
    kills: int
    deaths: int
    assists: int
    rounds_played: int
    casts_grenade: int
    casts_1: int
    casts_2: int
    casts_ult: int


@dataclass(frozen=True, slots=True)
class MatchRecord:
    match_uuid: str
    meta: MatchFilename
    map_internal_name: str
    game_version: str
    started_at: datetime
    duration_ms: int
    red_slug: str
    blue_slug: str
    winner_slug: str
    red_score: int
    blue_score: int
    players: tuple[PlayerRecord, ...]
    rounds: tuple[RoundRecord, ...]
    issues: tuple[Issue, ...] = field(default=())


def resolve_team_slugs(raw: RawMatch, meta: MatchFilename) -> dict[str, str]:
    won = {team.team_id: team.rounds_won for team in raw.teams}
    red, blue = won.get("Red"), won.get("Blue")
    if (meta.score_a, meta.score_b) == (red, blue):
        return {"Red": meta.team_a, "Blue": meta.team_b}
    if (meta.score_a, meta.score_b) == (blue, red):
        return {"Red": meta.team_b, "Blue": meta.team_a}
    raise MatchError(
        f"placar do arquivo {meta.score_a}x{meta.score_b} não bate com Red {red} x Blue {blue}"
    )


def round_sides(result: RoundResult) -> dict[str, Side]:
    winner = result.winning_team
    loser = "Blue" if winner == "Red" else "Red"
    winner_side: Side = "attack" if result.winning_team_role == "Attacker" else "defense"
    loser_side: Side = "defense" if winner_side == "attack" else "attack"
    return {winner: winner_side, loser: loser_side}


def result_code(result: RoundResult) -> str:
    if result.round_result_code:
        return result.round_result_code
    if "timer" in result.round_result.lower():
        return "Timeout"
    return "Unknown"


def kill_kind(kill: Kill, team_of: dict[str, str]) -> KillKind:
    if kill.killer is None or kill.killer == kill.victim:
        return "self"
    if team_of.get(kill.killer) == team_of.get(kill.victim):
        return "team"
    return "enemy"


def mark_first_kills_and_trades(kills: list[KillRecord], team_of: dict[str, str]) -> None:
    enemy_kills = [kill for kill in kills if kill.kind == "enemy"]
    if enemy_kills:
        enemy_kills[0].is_first_kill = True
    for later in enemy_kills:
        for earlier in enemy_kills:
            elapsed = later.t_round_ms - earlier.t_round_ms
            avenges_teammate = (
                earlier is not later
                and 0 <= elapsed <= TRADE_WINDOW_MS
                and earlier.killer == later.victim
                and team_of.get(earlier.victim) == team_of.get(later.killer)
            )
            if avenges_teammate:
                later.is_trade = True
                if earlier.traded_after_ms is None or elapsed < earlier.traded_after_ms:
                    earlier.traded_after_ms = elapsed


def _distance_m(a: tuple[int, int] | None, b: tuple[int, int]) -> float | None:
    if a is None:
        return None
    return round(math.dist(a, b) / UNITS_PER_METER, 2)


def _build_kills(
    result: RoundResult,
    team_of: dict[str, str],
    sides: dict[str, Side],
    reference: Reference,
    map_internal_name: str,
) -> list[KillRecord]:
    map_ref = reference.map(map_internal_name)
    raw_kills = sorted(
        (kill for stats in result.player_stats for kill in stats.kills),
        key=lambda kill: (kill.time_since_round_start_millis, kill.victim),
    )
    records: list[KillRecord] = []
    for seq, kill in enumerate(raw_kills):
        kind = kill_kind(kill, team_of)
        locations = {loc.puuid: loc for loc in kill.player_locations}
        killer_loc = locations.get(kill.killer) if kill.killer else None
        killer_xy = (killer_loc.location.x, killer_loc.location.y) if killer_loc else None
        victim_xy = (kill.victim_location.x, kill.victim_location.y)
        damage = kill.finishing_damage
        positions = []
        for loc in kill.player_locations:
            team = team_of.get(loc.puuid)
            if team is None:
                continue
            nx, ny = (
                map_ref.normalize(loc.location.x, loc.location.y) if map_ref else (None, None)
            )
            positions.append(
                PositionRecord(
                    loc.puuid, sides[team], loc.location.x, loc.location.y, nx, ny, loc.view_radians
                )
            )
        is_weapon = damage.damage_type == "Weapon"
        records.append(
            KillRecord(
                seq=seq,
                t_round_ms=kill.time_since_round_start_millis,
                t_game_ms=kill.time_since_game_start_millis,
                killer=None if kind == "self" else kill.killer,
                victim=kill.victim,
                kind=kind,
                damage_type=damage.damage_type,
                weapon_uuid=reference.weapon(damage.damage_item).uuid if is_weapon else None,
                ability_slot=damage.damage_item if damage.damage_type == "Ability" else None,
                is_secondary_fire=damage.is_secondary_fire_mode,
                killer_xy=killer_xy,
                victim_xy=victim_xy,
                distance_m=_distance_m(killer_xy, victim_xy) if kind == "enemy" else None,
                assistants=tuple(kill.assistants),
                positions=tuple(positions),
            )
        )
    mark_first_kills_and_trades(records, team_of)
    return records


def _build_round(
    result: RoundResult,
    team_of: dict[str, str],
    slugs: dict[str, str],
    reference: Reference,
    map_internal_name: str,
) -> RoundRecord:
    sides = round_sides(result)
    kills = _build_kills(result, team_of, sides, reference, map_internal_name)
    victims = {kill.victim for kill in kills}
    enemy_kills: dict[str, int] = defaultdict(int)
    for kill in kills:
        if kill.kind == "enemy" and kill.killer:
            enemy_kills[kill.killer] += 1

    players: list[RoundPlayerRecord] = []
    damage: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    for stats in result.player_stats:
        team = team_of.get(stats.puuid)
        if team is None:
            continue
        for hit in stats.damage:
            totals = damage[(stats.puuid, hit.receiver)]
            totals[0] += hit.damage
            totals[1] += hit.headshots
            totals[2] += hit.bodyshots
            totals[3] += hit.legshots
        economy = stats.economy
        players.append(
            RoundPlayerRecord(
                puuid=stats.puuid,
                team_slug=slugs[team],
                side=sides[team],
                score=stats.score,
                loadout_value=economy.loadout_value,
                spent=economy.spent,
                remaining=economy.remaining,
                weapon_uuid=reference.weapon(economy.weapon).uuid if economy.weapon else None,
                armor_uuid=reference.weapon(economy.armor).uuid if economy.armor else None,
                damage_dealt=sum(hit.damage for hit in stats.damage),
                headshots=sum(hit.headshots for hit in stats.damage),
                bodyshots=sum(hit.bodyshots for hit in stats.damage),
                legshots=sum(hit.legshots for hit in stats.damage),
                kills=enemy_kills[stats.puuid],
                died=stats.puuid in victims,
            )
        )

    attack_team = next(team for team, side in sides.items() if side == "attack")
    defense_team = next(team for team, side in sides.items() if side == "defense")
    planted = result.bomb_planter is not None
    defused = result.bomb_defuser is not None
    return RoundRecord(
        number=result.round_num,
        winner_slug=slugs[result.winning_team],
        winner_side=sides[result.winning_team],
        attack_slug=slugs[attack_team],
        defense_slug=slugs[defense_team],
        result_code=result_code(result),
        ceremony=result.round_ceremony or None,
        plant_site=(result.plant_site or None) if planted else None,
        plant_time_ms=result.plant_round_time if planted else None,
        planter=result.bomb_planter,
        plant_xy=(result.plant_location.x, result.plant_location.y) if planted else None,
        defuser=result.bomb_defuser,
        defuse_time_ms=result.defuse_round_time if defused else None,
        players=tuple(players),
        kills=tuple(kills),
        damage=tuple(
            DamageRecord(dealer, receiver, *totals) for (dealer, receiver), totals in damage.items()
        ),
    )


def _sanity_issues(raw: RawMatch, rounds: list[RoundRecord], source: str) -> list[Issue]:
    kills: dict[str, int] = defaultdict(int)
    deaths: dict[str, int] = defaultdict(int)
    assists: dict[str, int] = defaultdict(int)
    for round_ in rounds:
        for kill in round_.kills:
            if kill.kind == "enemy" and kill.killer:
                kills[kill.killer] += 1
            if kill.damage_type != "Bomb":
                deaths[kill.victim] += 1
            for assistant in kill.assistants:
                assists[assistant] += 1
    issues: list[Issue] = []
    for player in raw.players:
        if player.team_id not in PLAYING_TEAMS or player.stats is None:
            continue
        name = f"{player.game_name}#{player.tag_line}"
        for label, counted, expected in (
            ("kills", kills[player.puuid], player.stats.kills),
            ("deaths", deaths[player.puuid], player.stats.deaths),
            ("assists", assists[player.puuid], player.stats.assists),
        ):
            if counted != expected:
                issues.append(
                    Issue(
                        "warning",
                        f"{label}_mismatch",
                        source,
                        f"{name}: eventos somam {counted}, stats informa {expected}",
                    )
                )
    return issues


def transform_match(
    raw: RawMatch, meta: MatchFilename, reference: Reference, source: str
) -> MatchRecord:
    if not raw.match_info.is_completed:
        raise MatchError("partida marcada como não concluída")
    slugs = resolve_team_slugs(raw, meta)
    playing = [p for p in raw.players if p.team_id in PLAYING_TEAMS and not p.is_observer]
    team_of = {p.puuid: p.team_id for p in playing}
    map_internal_name = raw.match_info.map_id.rsplit("/", 1)[-1]

    rounds = [
        _build_round(result, team_of, slugs, reference, map_internal_name)
        for result in sorted(raw.round_results, key=lambda r: r.round_num)
    ]
    if not rounds:
        raise MatchError("partida sem rounds")
    first_sides = round_sides(min(raw.round_results, key=lambda r: r.round_num))

    players: list[PlayerRecord] = []
    for player in playing:
        if player.character_id is None or player.stats is None:
            raise MatchError(f"jogador sem agente ou estatísticas: {player.game_name}")
        casts = player.stats.ability_casts
        players.append(
            PlayerRecord(
                puuid=player.puuid,
                game_name=player.game_name,
                tag_line=player.tag_line,
                team_slug=slugs[player.team_id],
                agent_uuid=reference.agent(player.character_id).uuid,
                first_side=first_sides[player.team_id],
                score=player.stats.score,
                kills=player.stats.kills,
                deaths=player.stats.deaths,
                assists=player.stats.assists,
                rounds_played=player.stats.rounds_played,
                casts_grenade=casts.grenade_casts if casts else 0,
                casts_1=casts.ability1_casts if casts else 0,
                casts_2=casts.ability2_casts if casts else 0,
                casts_ult=casts.ultimate_casts if casts else 0,
            )
        )

    issues = _sanity_issues(raw, rounds, source)
    observers = len(raw.players) - len(playing)
    if observers:
        issues.append(Issue("info", "observer_removed", source, f"{observers} observador(es)"))
    timeouts = sum(1 for r in rounds if r.result_code == "Timeout")
    if timeouts:
        issues.append(Issue("info", "timeout_rounds", source, f"{timeouts} round(s) por tempo"))

    winner = next((team.team_id for team in raw.teams if team.won), None)
    if winner not in PLAYING_TEAMS:
        raise MatchError("partida sem time vencedor")
    won = {team.team_id: team.rounds_won for team in raw.teams}
    return MatchRecord(
        match_uuid=raw.match_info.match_id,
        meta=meta,
        map_internal_name=map_internal_name,
        game_version=raw.match_info.game_version,
        started_at=datetime.fromtimestamp(raw.match_info.game_start_millis / 1000, tz=UTC),
        duration_ms=raw.match_info.game_length_millis,
        red_slug=slugs["Red"],
        blue_slug=slugs["Blue"],
        winner_slug=slugs[winner],
        red_score=won["Red"],
        blue_score=won["Blue"],
        players=tuple(players),
        rounds=tuple(rounds),
        issues=tuple(issues),
    )
