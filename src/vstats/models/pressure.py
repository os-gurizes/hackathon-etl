from collections import defaultdict
from dataclasses import dataclass

import psycopg

from vstats.models.strategies import region_of

SITES = {"A", "B", "C"}
LOW_CLOCK_MS = 75_000
LOSING_STREAK = 3
MATCH_POINT = 12
EVENT_CONTEXTS = ("disadvantage", "advantage", "post_plant", "clutch", "low_clock")
ROUND_CONTEXTS = ("losing_streak", "match_point", "eco_vs_full_buy")

ROUNDS_SQL = """
    SELECT r.id, m.id, m.map_id, s.stage_id, r.number, r.attack_team_id, r.defense_team_id, r.winner_team_id,
           r.plant_time_ms, r.plant_site
    FROM analytics.rounds r
    JOIN analytics.matches m ON m.id = r.match_id
    JOIN analytics.series s ON s.id = m.series_id
    ORDER BY m.id, r.number
"""

KILLS_SQL = """
    SELECT k.round_id, k.t_round_ms, k.killer_id, k.victim_id, k.kind, k.victim_zone_id, k.killer_zone_id,
           coalesce(-ki.victim_delta, 0)
    FROM analytics.kills k
    LEFT JOIN analytics.kill_impact ki ON ki.kill_id = k.id
    ORDER BY k.round_id, k.seq
"""


@dataclass(frozen=True, slots=True)
class RoundInfo:
    round_id: int
    match_id: int
    map_id: int
    stage_id: int
    number: int
    attack_team: int
    defense_team: int
    winner_team: int
    plant_time_ms: int | None
    plant_site: str | None


@dataclass(frozen=True, slots=True)
class KillInfo:
    t: int
    killer: int | None
    victim: int
    kind: str
    victim_zone: int | None
    killer_zone: int | None
    killer_gain: float


def event_contexts(own_alive: int, enemy_alive: int, planted: bool, t: int, side: str) -> set[str]:
    contexts = set()
    if own_alive < enemy_alive:
        contexts.add("disadvantage")
    if own_alive > enemy_alive:
        contexts.add("advantage")
    if own_alive == 1 and enemy_alive >= 1:
        contexts.add("clutch")
    if planted:
        contexts.add("post_plant")
    if not planted and t >= LOW_CLOCK_MS and side == "attack":
        contexts.add("low_clock")
    return contexts


def detect_rotations(
    samples: list[tuple[int, str]], site_events: list[tuple[int, str]]
) -> list[tuple[str, str, int, int, bool]]:
    rotations = []
    last_site: tuple[int, str] | None = None
    for t, region in samples:
        if region not in SITES:
            continue
        if last_site is not None and last_site[1] != region:
            t1, r1 = last_site
            informed = any(te <= t1 and er == region for te, er in site_events)
            rotations.append((r1, region, t1, t, informed))
        last_site = (t, region)
    return rotations


def _enemies(alive_by_team: dict[int, int], team: int) -> int:
    return sum(n for other, n in alive_by_team.items() if other != team)


def build_pressure(conn: psycopg.Connection) -> dict[str, int]:
    zone_region = {z: region_of(sup) for z, sup in conn.execute("SELECT id, super_region FROM analytics.zones")}
    rounds = [RoundInfo(*row) for row in conn.execute(ROUNDS_SQL)]
    players: dict[int, dict[int, int]] = defaultdict(dict)
    for round_id, player_id, team_id in conn.execute("SELECT round_id, player_id, team_id FROM analytics.round_players"):
        players[round_id][player_id] = team_id
    kills: dict[int, list[KillInfo]] = defaultdict(list)
    for round_id, *fields in conn.execute(KILLS_SQL):
        kills[round_id].append(KillInfo(*fields))
    buys = {
        (round_id, team_id): buy
        for round_id, team_id, buy in conn.execute("SELECT round_id, team_id, buy_type FROM analytics.round_team_economy")
    }
    samples: dict[tuple[int, int], list[tuple[int, str]]] = defaultdict(list)
    for round_id, player_id, t, zone in conn.execute(
        "SELECT round_id, player_id, t_round_ms, zone_id FROM analytics.position_samples WHERE zone_id IS NOT NULL ORDER BY t_round_ms"
    ):
        samples[(round_id, player_id)].append((t, zone_region[zone]))

    stats: dict[tuple, list[float]] = defaultdict(lambda: [0, 0, 0, 0, 0, 0.0])
    rotation_rows: list[tuple] = []
    score: dict[tuple[int, int], int] = defaultdict(int)
    streak: dict[tuple[int, int], int] = defaultdict(int)
    for info in rounds:
        team_of = players[info.round_id]
        side_of_team = {info.attack_team: "attack", info.defense_team: "defense"}
        planted_at = info.plant_time_ms
        alive = {team: {p for p, t in team_of.items() if t == team} for team in side_of_team}
        died_at: dict[int, int] = {}
        round_contexts: dict[int, set[str]] = defaultdict(set)
        event_counts: dict[tuple[int, str], list[float]] = defaultdict(lambda: [0, 0, 0.0])

        for team in side_of_team:
            opponent = info.defense_team if team == info.attack_team else info.attack_team
            if streak[(info.match_id, team)] >= LOSING_STREAK:
                round_contexts[team].add("losing_streak")
            if max(score[(info.match_id, team)], score[(info.match_id, opponent)]) >= MATCH_POINT:
                round_contexts[team].add("match_point")
            if buys.get((info.round_id, team)) in ("eco", "semi_eco") and buys.get((info.round_id, opponent)) == "full_buy":
                round_contexts[team].add("eco_vs_full_buy")

        exposed: dict[int, set[str]] = defaultdict(set)

        def expose(t: int) -> None:
            planted = planted_at is not None and planted_at <= t
            for team, members in alive.items():
                enemy = sum(len(m) for other, m in alive.items() if other != team)
                for context in event_contexts(len(members), enemy, planted, t, side_of_team[team]):
                    for player in members:
                        exposed[player].add(context)

        expose(0)
        for kill in kills[info.round_id]:
            planted = planted_at is not None and planted_at <= kill.t
            victim_team = team_of.get(kill.victim)
            if victim_team is None:
                continue
            before = {team: len(m) for team, m in alive.items()}
            if kill.kind == "enemy" and kill.killer in team_of:
                killer_team = team_of[kill.killer]
                for context in event_contexts(before[killer_team], _enemies(before, killer_team), planted, kill.t, side_of_team[killer_team]):
                    event_counts[(kill.killer, context)][0] += 1
                    event_counts[(kill.killer, context)][2] += kill.killer_gain
            for context in event_contexts(before[victim_team], _enemies(before, victim_team), planted, kill.t, side_of_team[victim_team]):
                event_counts[(kill.victim, context)][1] += 1
                event_counts[(kill.victim, context)][2] -= kill.killer_gain
            alive[victim_team].discard(kill.victim)
            died_at[kill.victim] = kill.t
            expose(kill.t)

        for player, team in team_of.items():
            side = side_of_team[team]
            won = info.winner_team == team
            survived = player not in died_at
            for context in exposed[player] | round_contexts[team]:
                key = (player, team, info.map_id, info.stage_id, side, context)
                kills_, deaths_, delta = event_counts.get((player, context), [0, 0, 0.0])
                if context in ROUND_CONTEXTS:
                    kills_ = sum(1 for k in kills[info.round_id] if k.killer == player and k.kind == "enemy")
                    deaths_ = int(not survived)
                    delta = sum(k.killer_gain for k in kills[info.round_id] if k.killer == player and k.kind == "enemy")
                    delta -= sum(k.killer_gain for k in kills[info.round_id] if k.victim == player)
                row = stats[key]
                row[0] += 1
                row[1] += won
                row[2] += survived
                row[3] += kills_
                row[4] += deaths_
                row[5] += delta

            site_events = [
                (k.t, region)
                for k in kills[info.round_id]
                for zone in (k.victim_zone, k.killer_zone)
                if zone is not None and (region := zone_region[zone]) in SITES
            ]
            if planted_at is not None and info.plant_site:
                site_events.append((planted_at, info.plant_site))
            for from_region, to_region, t1, t2, informed in detect_rotations(samples[(info.round_id, player)], site_events):
                source_fell = bool(info.plant_site == from_region and planted_at is not None and planted_at > t1)
                rotation_rows.append((info.round_id, player, team, info.map_id, side, from_region, to_region,
                                      t1, t2, informed, source_fell, won))

        winner, loser = info.winner_team, (info.defense_team if info.winner_team == info.attack_team else info.attack_team)
        score[(info.match_id, winner)] += 1
        streak[(info.match_id, winner)] = 0
        streak[(info.match_id, loser)] += 1

    with conn.transaction():
        conn.execute("TRUNCATE analytics.pressure_stats, analytics.rotations")
        with conn.cursor() as cur:
            with cur.copy(
                """COPY analytics.pressure_stats (player_id, team_id, map_id, stage_id, side, context, rounds,
                       rounds_won, survived, kills, deaths, wp_delta) FROM STDIN"""
            ) as copy:
                for key, values in stats.items():
                    copy.write_row((*key, *values))
            with cur.copy(
                """COPY analytics.rotations (round_id, player_id, team_id, map_id, side, from_region, to_region,
                       left_after_ms, seen_at_ms, informed, source_fell, round_won) FROM STDIN"""
            ) as copy:
                for row in rotation_rows:
                    copy.write_row(row)
    return {"pressure_stats": len(stats), "rotations": len(rotation_rows)}
