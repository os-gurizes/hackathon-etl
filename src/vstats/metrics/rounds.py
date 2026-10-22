from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class KillEvent:
    seq: int
    killer_id: int | None
    victim_id: int
    kind: str
    damage_type: str
    is_first_kill: bool
    is_trade: bool
    traded: bool
    assistants: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class RoundPlayerStats:
    player_id: int
    kills: int
    deaths: int
    assists: int
    kast: bool
    first_kill: bool
    first_death: bool
    trade_kills: int
    traded_death: bool
    clutch_size: int | None
    clutch_won: bool | None


def clutches(team_of: dict[int, int], kills: list[KillEvent]) -> dict[int, int]:
    alive: dict[int, set[int]] = defaultdict(set)
    for player, team in team_of.items():
        alive[team].add(player)
    found: dict[int, int] = {}
    for kill in sorted(kills, key=lambda k: k.seq):
        team = team_of.get(kill.victim_id)
        if team is None:
            continue
        alive[team].discard(kill.victim_id)
        for side_team, members in alive.items():
            enemies = sum(len(m) for t, m in alive.items() if t != side_team)
            if len(members) == 1 and enemies >= 1:
                [survivor] = members
                found.setdefault(survivor, enemies)
    return found


def round_player_stats(
    team_of: dict[int, int], winner_team: int, kills: list[KillEvent]
) -> list[RoundPlayerStats]:
    counted_kills: dict[int, int] = defaultdict(int)
    trade_kills: dict[int, int] = defaultdict(int)
    assists: dict[int, int] = defaultdict(int)
    deaths: dict[int, int] = defaultdict(int)
    died: set[int] = set()
    traded: set[int] = set()
    first_killer: int | None = None
    first_victim: int | None = None
    for kill in kills:
        died.add(kill.victim_id)
        if kill.damage_type != "Bomb":
            deaths[kill.victim_id] += 1
        for assistant in kill.assistants:
            assists[assistant] += 1
        if kill.kind != "enemy" or kill.killer_id is None:
            continue
        counted_kills[kill.killer_id] += 1
        if kill.is_trade:
            trade_kills[kill.killer_id] += 1
        if kill.traded:
            traded.add(kill.victim_id)
        if kill.is_first_kill:
            first_killer, first_victim = kill.killer_id, kill.victim_id

    clutch = clutches(team_of, kills)
    return [
        RoundPlayerStats(
            player_id=player,
            kills=counted_kills[player],
            deaths=deaths[player],
            assists=assists[player],
            kast=bool(counted_kills[player] or assists[player] or player not in died or player in traded),
            first_kill=player == first_killer,
            first_death=player == first_victim,
            trade_kills=trade_kills[player],
            traded_death=player in traded,
            clutch_size=clutch.get(player),
            clutch_won=(team == winner_team) if player in clutch else None,
        )
        for player, team in sorted(team_of.items())
    ]
