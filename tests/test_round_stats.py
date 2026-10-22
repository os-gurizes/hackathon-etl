from vstats.metrics.rounds import KillEvent, clutches, round_player_stats

RED, BLUE = 1, 2
TEAM_OF = {1: RED, 2: RED, 3: RED, 4: RED, 5: RED, 6: BLUE, 7: BLUE, 8: BLUE, 9: BLUE, 10: BLUE}


def kill(seq: int, killer: int | None, victim: int, *, kind: str = "enemy", damage_type: str = "Weapon",
         first: bool = False, trade: bool = False, traded: bool = False, assistants: tuple[int, ...] = ()) -> KillEvent:
    return KillEvent(seq, killer, victim, kind, damage_type, first, trade, traded, assistants)


def by_player(kills: list[KillEvent], winner: int = RED) -> dict:
    return {s.player_id: s for s in round_player_stats(TEAM_OF, winner, kills)}


def test_kast_counts_kill_assist_survival_and_trade() -> None:
    kills = [
        kill(0, 6, 1, first=True, traded=True),
        kill(1, 2, 6, trade=True, assistants=(3,)),
        kill(2, 7, 4),
    ]
    stats = by_player(kills)
    assert stats[1].kast and stats[1].traded_death
    assert stats[2].kast and stats[2].trade_kills == 1
    assert stats[3].kast and stats[3].assists == 1
    assert not stats[4].kast
    assert stats[5].kast
    assert stats[6].first_kill and stats[1].first_death


def test_bomb_deaths_do_not_count_but_break_kast() -> None:
    stats = by_player([kill(0, None, 1, kind="self", damage_type="Bomb")])
    assert stats[1].deaths == 0 and not stats[1].kast


def test_team_kill_is_not_a_kill() -> None:
    stats = by_player([kill(0, 2, 1, kind="team")])
    assert stats[2].kills == 0 and stats[1].deaths == 1


def test_clutch_detects_last_player_and_enemy_count() -> None:
    kills = [kill(i, 6, victim) for i, victim in enumerate((1, 2, 3, 4))]
    kills += [kill(4, 5, 6), kill(5, 5, 7)]
    assert clutches(TEAM_OF, kills) == {5: 5}
    stats = by_player(kills, winner=RED)
    assert stats[5].clutch_size == 5 and stats[5].clutch_won
    assert stats[6].clutch_size is None


def test_both_sides_can_reach_a_clutch_in_the_same_round() -> None:
    kills = [kill(i, 5, 6 + i) for i in range(4)] + [kill(4 + i, 10, 1 + i) for i in range(4)]
    stats = by_player(kills, winner=BLUE)
    assert stats[5].clutch_size == 1 and stats[5].clutch_won is False
    assert stats[10].clutch_size == 5 and stats[10].clutch_won is True
