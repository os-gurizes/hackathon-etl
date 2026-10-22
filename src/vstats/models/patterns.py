import math
from collections import Counter, defaultdict
from dataclasses import dataclass

import numpy as np
import psycopg
from numpy.typing import NDArray
from scipy.stats import binom

MIN_ROUNDS = 15
MIN_OCCURRENCES = 3
ALPHA = 0.1
ISOLATION_RADIUS = 1_500
PREDICTABLE_PERCENTILE = 10
MAX_EVIDENCE = 8

PLAYER_ROUNDS_SQL = """
    SELECT rp.player_id, m.map_id, rp.side, a.role, r.id, m.id, r.number
    FROM analytics.round_players rp
    JOIN analytics.rounds r ON r.id = rp.round_id
    JOIN analytics.matches m ON m.id = r.match_id
    JOIN analytics.match_players mp ON mp.match_id = m.id AND mp.player_id = rp.player_id
    JOIN analytics.agents a ON a.id = mp.agent_id
"""

DEATHS_SQL = f"""
    SELECT k.id, k.round_id, k.victim_id, k.victim_zone_id, k.is_first_kill, k.traded_after_ms IS NOT NULL,
           -ki.victim_delta,
           EXISTS (
               SELECT 1 FROM analytics.position_samples ps
               WHERE ps.kill_id = k.id AND ps.player_id <> k.victim_id AND ps.side = rp.side
                 AND (ps.x - k.victim_x) ^ 2 + (ps.y - k.victim_y) ^ 2 < {ISOLATION_RADIUS} ^ 2
           )
    FROM analytics.kills k
    JOIN analytics.round_players rp ON rp.round_id = k.round_id AND rp.player_id = k.victim_id
    JOIN analytics.kill_impact ki ON ki.kill_id = k.id
    WHERE k.kind = 'enemy'
"""


def benjamini_hochberg(p_values: NDArray[np.float64]) -> NDArray[np.float64]:
    n = len(p_values)
    if n == 0:
        return p_values
    order = np.argsort(p_values)
    ranked = p_values[order] * n / np.arange(1, n + 1)
    adjusted = np.minimum.accumulate(ranked[::-1])[::-1]
    result = np.empty(n)
    result[order] = np.minimum(adjusted, 1.0)
    return result


def binomial_p(occurrences: int, trials: int, p: float) -> float:
    return float(binom.sf(occurrences - 1, trials, min(max(p, 1e-9), 1.0)))


def normalized_entropy(zones: list[int]) -> float:
    counts = Counter(zones)
    if len(zones) < 2 or len(counts) < 2:
        return 0.0
    probs = np.array(list(counts.values())) / len(zones)
    return float(-(probs * np.log(probs)).sum() / math.log(len(zones)))


@dataclass
class Finding:
    player_id: int
    map_id: int
    side: str
    pattern: str
    zone_id: int | None
    rounds: int
    occurrences: int
    expected: float
    baseline_rate: float
    p_value: float | None
    cost_rounds: float
    evidence: list[int]


@dataclass(frozen=True, slots=True)
class Death:
    round_id: int
    zone_id: int | None
    first: bool
    traded: bool
    wp_loss: float
    supported: bool


def _load(conn: psycopg.Connection) -> tuple[dict, dict, dict, dict]:
    rounds_of: dict[tuple[int, int, str], list[int]] = defaultdict(list)
    role_of: dict[tuple[int, int, str], str] = {}
    round_order: dict[int, tuple[int, int]] = {}
    for player, map_id, side, role, round_id, match_id, number in conn.execute(PLAYER_ROUNDS_SQL):
        key = (player, map_id, side)
        rounds_of[key].append(round_id)
        role_of[key] = role or "?"
        round_order[round_id] = (match_id, number)
    deaths: dict[tuple[int, int, str], list[Death]] = defaultdict(list)
    side_of = {(rid, key[0]): key for key, rids in rounds_of.items() for rid in rids}
    for _, round_id, victim, zone, first, traded, wp_loss, supported in conn.execute(DEATHS_SQL):
        key = side_of.get((round_id, victim))
        if key is not None:
            deaths[key].append(Death(round_id, zone, first, traded, float(wp_loss), supported))
    return rounds_of, role_of, round_order, deaths


def _first_death_zone(rounds_of: dict, deaths: dict) -> list[Finding]:
    totals: Counter[tuple[int, str]] = Counter()
    zone_counts: Counter[tuple[int, str, int]] = Counter()
    for (player, map_id, side), rids in rounds_of.items():
        totals[(map_id, side)] += len(rids)
    for (player, map_id, side), items in deaths.items():
        for d in items:
            if d.first and d.zone_id is not None:
                zone_counts[(map_id, side, d.zone_id)] += 1
    findings = []
    for key, items in deaths.items():
        player, map_id, side = key
        n = len(rounds_of[key])
        if n < MIN_ROUNDS:
            continue
        by_zone: dict[int, list[Death]] = defaultdict(list)
        for d in items:
            if d.first and d.zone_id is not None:
                by_zone[d.zone_id].append(d)
        for zone, events in by_zone.items():
            p0 = zone_counts[(map_id, side, zone)] / totals[(map_id, side)]
            if len(events) < MIN_OCCURRENCES:
                continue
            expected = n * p0
            loss = float(np.mean([e.wp_loss for e in events]))
            findings.append(Finding(player, map_id, side, "first_death_zone", zone, n, len(events), expected, p0,
                                    binomial_p(len(events), n, p0), (len(events) - expected) * loss,
                                    [e.round_id for e in events]))
    return findings


def _isolated_deaths(rounds_of: dict, role_of: dict, deaths: dict) -> list[Finding]:
    def group(key: tuple[int, int, str]) -> tuple[str, int, str]:
        return role_of[key], key[1], key[2]

    role_rounds: Counter[tuple[str, int, str]] = Counter()
    role_isolated: Counter[tuple[str, int, str]] = Counter()
    for key, rids in rounds_of.items():
        role_rounds[group(key)] += len(rids)
    for key, items in deaths.items():
        role_isolated[group(key)] += sum(1 for d in items if not d.supported and not d.traded)
    findings = []
    for key, items in deaths.items():
        player, map_id, side = key
        n = len(rounds_of[key])
        events = [d for d in items if not d.supported and not d.traded]
        if n < MIN_ROUNDS or len(events) < MIN_OCCURRENCES:
            continue
        p0 = role_isolated[group(key)] / role_rounds[group(key)]
        expected = n * p0
        loss = float(np.mean([e.wp_loss for e in events]))
        findings.append(Finding(player, map_id, side, "isolated_death", None, n, len(events), expected, p0,
                                binomial_p(len(events), n, p0), (len(events) - expected) * loss,
                                [e.round_id for e in events]))
    return findings


def _repeat_after_first_death(rounds_of: dict, round_order: dict, deaths: dict) -> list[Finding]:
    zone_rate: Counter[tuple[int, str, int]] = Counter()
    totals: Counter[tuple[int, str]] = Counter()
    for (player, map_id, side), rids in rounds_of.items():
        totals[(map_id, side)] += len(rids)
    for (player, map_id, side), items in deaths.items():
        for d in items:
            if d.first and d.zone_id is not None:
                zone_rate[(map_id, side, d.zone_id)] += 1
    findings = []
    for key, items in deaths.items():
        player, map_id, side = key
        first = {round_order[d.round_id]: d for d in items if d.first and d.zone_id is not None}
        played = {round_order[r] for r in rounds_of[key]}
        trials, repeats, expected, evidence, losses = 0, 0, 0.0, [], []
        for (match_id, number), death in first.items():
            if (match_id, number + 1) not in played:
                continue
            trials += 1
            expected += zone_rate[(map_id, side, death.zone_id)] / totals[(map_id, side)]
            following = first.get((match_id, number + 1))
            if following is not None and following.zone_id == death.zone_id:
                repeats += 1
                evidence.append(following.round_id)
                losses.append(following.wp_loss)
        if trials < MIN_OCCURRENCES or repeats < MIN_OCCURRENCES:
            continue
        p0 = expected / trials
        findings.append(Finding(player, map_id, side, "repeat_after_first_death", None, trials, repeats, expected, p0,
                                binomial_p(repeats, trials, p0), (repeats - expected) * float(np.mean(losses)), evidence))
    return findings


def _predictable_route(
    conn: psycopg.Connection, rounds_of: dict, role_of: dict, deaths: dict
) -> list[Finding]:
    zone_samples: dict[tuple[int, int], int] = {}
    for row in conn.execute(
        """SELECT DISTINCT ON (ps.round_id, ps.player_id) ps.round_id, ps.player_id, ps.zone_id
           FROM analytics.position_samples ps WHERE ps.zone_id IS NOT NULL
           ORDER BY ps.round_id, ps.player_id, ps.t_round_ms"""
    ):
        zone_samples[(row[0], row[1])] = row[2]
    entropy: dict[tuple[int, int, str], float] = {}
    for key, rids in rounds_of.items():
        zones = [zone_samples[(rid, key[0])] for rid in rids if (rid, key[0]) in zone_samples]
        if len(zones) >= MIN_ROUNDS:
            entropy[key] = normalized_entropy(zones)
    by_role: dict[str, list[float]] = defaultdict(list)
    for key, value in entropy.items():
        by_role[role_of[key]].append(value)
    thresholds = {role: float(np.percentile(values, PREDICTABLE_PERCENTILE)) for role, values in by_role.items()}

    first_rate: Counter[tuple[int, str]] = Counter()
    totals: Counter[tuple[int, str]] = Counter()
    for key, rids in rounds_of.items():
        totals[(key[1], key[2])] += len(rids)
    for key, items in deaths.items():
        first_rate[(key[1], key[2])] += sum(d.first for d in items)
    findings = []
    for key, value in entropy.items():
        if value > thresholds[role_of[key]]:
            continue
        player, map_id, side = key
        n = len(rounds_of[key])
        firsts = [d for d in deaths.get(key, []) if d.first]
        p0 = first_rate[(map_id, side)] / totals[(map_id, side)]
        expected = n * p0
        loss = float(np.mean([d.wp_loss for d in firsts])) if firsts else 0.0
        findings.append(Finding(player, map_id, side, "predictable_route", None, n, len(firsts), expected, p0,
                                binomial_p(len(firsts), n, p0) if firsts else None,
                                (len(firsts) - expected) * loss, [d.round_id for d in firsts]))
    return findings


def build_patterns(conn: psycopg.Connection) -> Counter[str]:
    rounds_of, role_of, round_order, deaths = _load(conn)
    findings = (
        _first_death_zone(rounds_of, deaths)
        + _isolated_deaths(rounds_of, role_of, deaths)
        + _repeat_after_first_death(rounds_of, round_order, deaths)
        + _predictable_route(conn, rounds_of, role_of, deaths)
    )
    p_values = np.array([f.p_value if f.p_value is not None else 1.0 for f in findings])
    adjusted = benjamini_hochberg(p_values)
    significant: Counter[str] = Counter()
    with conn.transaction():
        conn.execute("TRUNCATE analytics.player_patterns")
        with conn.cursor() as cur, cur.copy(
            """COPY analytics.player_patterns (player_id, map_id, side, pattern, zone_id, rounds, occurrences,
                   expected, rate, baseline_rate, p_value, p_adjusted, cost_rounds, significant, evidence_round_ids)
               FROM STDIN"""
        ) as copy:
            for f, p_adj in zip(findings, adjusted, strict=True):
                is_significant = bool(p_adj < ALPHA and f.occurrences > f.expected and f.cost_rounds > 0)
                significant[f.pattern] += is_significant
                copy.write_row((
                    f.player_id, f.map_id, f.side, f.pattern, f.zone_id, f.rounds, f.occurrences, f.expected,
                    f.occurrences / f.rounds, f.baseline_rate, f.p_value, float(p_adj), f.cost_rounds,
                    is_significant, f.evidence[:MAX_EVIDENCE],
                ))
    return significant
