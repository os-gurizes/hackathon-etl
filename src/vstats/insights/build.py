from collections import Counter
from dataclasses import dataclass, field

import psycopg

from vstats.insights import templates as t

MIN_FLAG_ROUNDS = 3
MIN_PRESSURE_ROUNDS = 30
PRESSURE_DROP_RATIO = 0.75
MIN_CLUTCHES = 10
MIN_ROTATIONS = 10
MIN_STRATEGY_ROUNDS = 8
MIN_OVERUSE_MATCHES = 3
MIN_OVERUSE_SHARE = 0.25
BEST_STRATEGY_ABOVE = 0.55
WORST_STRATEGY_BELOW = 0.45
MIN_ULT_DECIDED = 3
MIN_COMBO = 10
MIN_AGENT_MATCHES = 3
MIN_MAP_MATCHES = 3
MIN_PLAYER_MATCHES = 5


@dataclass
class Insight:
    scope: str
    scope_id: int
    kind: str
    polarity: str
    severity: int
    title: str
    body: str
    sample_size: int
    confidence: float
    map_id: int | None = None
    side: str | None = None
    metric_value: float | None = None
    baseline_value: float | None = None
    is_estimate: bool = False
    evidence: list[int] = field(default_factory=list)


def _patterns(conn: psycopg.Connection) -> list[Insight]:
    rows = conn.execute(
        """SELECT pp.player_id, pp.map_id, m.name, pp.side, pp.pattern, z.name, pp.rounds, pp.occurrences, pp.rate,
                  pp.baseline_rate, pp.cost_rounds, pp.p_adjusted, pp.evidence_round_ids,
                  (SELECT count(DISTINCT s.match_id) FROM analytics.player_match_stats s
                   WHERE s.player_id = pp.player_id AND s.map_id = pp.map_id)
           FROM analytics.player_patterns pp
           JOIN analytics.maps m ON m.id = pp.map_id
           LEFT JOIN analytics.zones z ON z.id = pp.zone_id
           WHERE pp.significant"""
    ).fetchall()
    insights = []
    for player, map_id, map_name, side, pattern, zone, rounds, occ, rate, base, cost, p_adj, evidence, matches in rows:
        if pattern == "first_death_zone":
            title, body = t.first_death_zone(map_name, side, zone, rate, base, cost, matches)
        elif pattern == "isolated_death":
            title, body = t.isolated_death(map_name, side, rate, base, cost, matches)
        elif pattern == "predictable_route":
            title, body = t.predictable_route(map_name, side, rate, base, cost)
        else:
            title, body = t.repeat_after_first_death(map_name, side, occ, cost)
        insights.append(Insight("player", player, "repetitive_pattern", "negative", t.severity_for_cost(cost),
                                title, body, rounds, 1 - p_adj, map_id, side, rate, base, False, list(evidence)))
    return insights


def _economy(conn: psycopg.Connection) -> list[Insight]:
    insights = []
    for scope, column in (("team", "team_id"), ("player", "player_id")):
        rows = conn.execute(
            f"""SELECT f.{column}, f.flag, count(*), sum(f.won::int), sum(f.expected_win), avg(f.expected_win),
                       (array_agg(f.round_id ORDER BY f.expected_win - f.won::int DESC))[1:8]
                FROM analytics.economy_flags f
                WHERE f.{column} IS NOT NULL AND ({'f.player_id IS NULL' if scope == 'team' else 'f.player_id IS NOT NULL'})
                GROUP BY 1, 2
                HAVING count(*) >= {MIN_FLAG_ROUNDS} AND sum(f.expected_win) - sum(f.won::int) > 0"""
        ).fetchall()
        for scope_id, flag, n, won, expected, expected_rate, evidence in rows:
            cost = expected - won
            title, template = t.ECONOMY[flag]
            body = template.format(n=n, won=won, expected=t.number(expected), expected_rate=t.percent(expected_rate),
                                   cost=t.rounds_text(cost))
            insights.append(Insight(scope, scope_id, "economy", "negative", t.severity_for_cost(cost), title, body,
                                    n, min(1.0, n / 20), metric_value=won / n, baseline_value=expected_rate,
                                    evidence=list(evidence)))
    return insights


def _pressure(conn: psycopg.Connection) -> list[Insight]:
    rows = conn.execute(
        f"""WITH player AS (
                SELECT player_id, context, sum(rounds) AS rounds, sum(kills) AS kills, sum(deaths) AS deaths
                FROM analytics.pressure_stats GROUP BY 1, 2
            ),
            overall AS (
                SELECT player_id, sum(kills)::real / greatest(sum(deaths), 1) AS kd
                FROM analytics.player_match_stats GROUP BY 1
            ),
            baseline AS (
                SELECT context, sum(kills)::real / greatest(sum(deaths), 1) AS kd FROM analytics.pressure_stats GROUP BY 1
            )
            SELECT p.player_id, p.context, p.rounds, p.kills::real / greatest(p.deaths, 1), o.kd, b.kd
            FROM player p JOIN overall o USING (player_id) JOIN baseline b USING (context)
            WHERE p.rounds >= {MIN_PRESSURE_ROUNDS} AND p.context <> 'advantage'"""
    ).fetchall()
    insights = []
    for player, context, rounds, kd, own_kd, base in rows:
        if kd < base * PRESSURE_DROP_RATIO and kd < own_kd * PRESSURE_DROP_RATIO:
            title, body = t.pressure_drop(context, kd, own_kd, base)
            severity = 3 if kd < base * 0.5 else 2
            insights.append(Insight("player", player, "pressure", "negative", severity, title, body, rounds,
                                    min(1.0, rounds / 100), metric_value=kd, baseline_value=base))
    clutch_rows = conn.execute(
        f"""WITH player AS (
                SELECT player_id, sum(clutch_wins) AS won, sum(clutch_attempts) AS attempts
                FROM analytics.player_match_stats GROUP BY 1
            ), overall AS (SELECT sum(clutch_wins)::real / sum(clutch_attempts) AS rate FROM analytics.player_match_stats)
            SELECT p.player_id, p.won, p.attempts, p.won::real / p.attempts, o.rate
            FROM player p, overall o
            WHERE p.attempts >= {MIN_CLUTCHES} AND p.won::real / p.attempts >= 2 * o.rate"""
    ).fetchall()
    for player, won, attempts, rate, base in clutch_rows:
        title, body = t.clutch_strength(won, attempts, rate, base)
        insights.append(Insight("player", player, "pressure", "positive", 1, title, body, attempts,
                                min(1.0, attempts / 30), metric_value=rate, baseline_value=base))
    return insights


def _rotations(conn: psycopg.Connection) -> list[Insight]:
    rows = conn.execute(
        f"""SELECT team_id, count(*) FILTER (WHERE NOT informed),
                   avg(source_fell::int) FILTER (WHERE NOT informed), avg(source_fell::int) FILTER (WHERE informed),
                   (array_agg(round_id) FILTER (WHERE NOT informed AND source_fell))[1:8]
            FROM analytics.rotations WHERE side = 'defense'
            GROUP BY 1
            HAVING count(*) FILTER (WHERE NOT informed) >= {MIN_ROTATIONS}"""
    ).fetchall()
    insights = []
    for team, n, fell, informed_fell, evidence in rows:
        if fell is None or informed_fell is None or fell <= informed_fell:
            continue
        title, body = t.rotation_without_info(n, fell, informed_fell)
        severity = 3 if fell >= 2 * informed_fell and n >= 30 else 2
        insights.append(Insight("team", team, "rotation", "negative", severity, title, body, n, min(1.0, n / 50),
                                side="defense", metric_value=fell, baseline_value=informed_fell, is_estimate=True,
                                evidence=list(evidence or [])))
    return insights


def _abilities(conn: psycopg.Connection) -> list[Insight]:
    insights = []
    for player, flagged, total in conn.execute(
        f"""SELECT player_id, count(*) FILTER (WHERE likely_overuse), count(*) FROM analytics.ability_usage
            GROUP BY 1
            HAVING count(*) FILTER (WHERE likely_overuse) >= {MIN_OVERUSE_MATCHES}
               AND count(*) FILTER (WHERE likely_overuse)::real / count(*) >= {MIN_OVERUSE_SHARE}"""
    ):
        title, body = t.overuse(flagged, total)
        insights.append(Insight("player", player, "ability_estimate", "negative", 1, title, body, total,
                                min(1.0, total / 20), metric_value=flagged / total, is_estimate=True))
    for player, decided, total in conn.execute(
        f"""SELECT player_id, sum(ult_kills_decided), sum(ult_kills) FROM analytics.ability_usage
            GROUP BY 1 HAVING sum(ult_kills_decided) >= {MIN_ULT_DECIDED}"""
    ):
        title, body = t.ult_in_decided_rounds(decided, total)
        insights.append(Insight("player", player, "ability_estimate", "negative", 1, title, body, total,
                                min(1.0, total / 20), metric_value=decided / total, is_estimate=True))
    for team, map_id, map_name, a, b, n, control in conn.execute(
        f"""SELECT DISTINCT ON (c.team_id, c.map_id) c.team_id, c.map_id, m.name, pa.game_name, pb.game_name,
                   sum(c.occurrences), sum(c.site_control)::real / sum(c.occurrences)
            FROM analytics.combos c
            JOIN analytics.maps m ON m.id = c.map_id
            JOIN analytics.players pa ON pa.id = c.player_a
            JOIN analytics.players pb ON pb.id = c.player_b
            GROUP BY c.team_id, c.map_id, m.name, pa.game_name, pb.game_name
            HAVING sum(c.occurrences) >= {MIN_COMBO}
            ORDER BY c.team_id, c.map_id, sum(c.site_control)::real / sum(c.occurrences) DESC"""
    ):
        title, body = t.combo(a, b, map_name, n, control)
        insights.append(Insight("team", team, "combo", "positive", 1, title, body, n, min(1.0, n / 40),
                                map_id, metric_value=control, is_estimate=True))
    return insights


def _strategies(conn: psycopg.Connection) -> list[Insight]:
    rows = conn.execute(
        f"""SELECT rs.team_id, s.map_id, m.name, s.side, s.title, count(*), avg(rs.won::int),
                   (array_agg(rs.round_id))[1:8]
            FROM analytics.round_strategy rs
            JOIN analytics.strategies s ON s.id = rs.strategy_id
            JOIN analytics.maps m ON m.id = s.map_id
            WHERE NOT s.is_noise
            GROUP BY 1, 2, 3, 4, 5
            HAVING count(*) >= {MIN_STRATEGY_ROUNDS}"""
    ).fetchall()
    by_group: dict[tuple[int, int, str], list[tuple]] = {}
    for row in rows:
        by_group.setdefault((row[0], row[1], row[3]), []).append(row)
    insights = []
    for (team, map_id, side), items in by_group.items():
        if len(items) < 2:
            continue
        ordered = sorted(items, key=lambda r: r[6])
        for row, best in ((ordered[-1], True), (ordered[0], False)):
            _, _, map_name, _, title_text, n, rate, evidence = row
            if (best and rate <= BEST_STRATEGY_ABOVE) or (not best and rate >= WORST_STRATEGY_BELOW):
                continue
            title, body = t.strategy(map_name, side, title_text, rate, n, best)
            insights.append(Insight("team", team, "strategy", "positive" if best else "negative", 1, title, body, n,
                                    min(1.0, n / 30), map_id, side, rate, evidence=list(evidence)))
    return insights


def _strengths(conn: psycopg.Connection) -> list[Insight]:
    insights = []
    for player, map_id, map_name, agent, acs, base, matches in conn.execute(
        f"""SELECT DISTINCT ON (s.player_id) s.player_id, s.map_id, m.name, a.name,
                   sum(s.score)::real / sum(s.rounds), ams.acs, count(DISTINCT s.match_id)
            FROM analytics.player_match_stats s
            JOIN analytics.maps m ON m.id = s.map_id
            JOIN analytics.agents a ON a.id = s.agent_id
            JOIN analytics.agent_map_stats ams ON ams.map_id = s.map_id AND ams.agent_id = s.agent_id
            GROUP BY s.player_id, s.map_id, m.name, a.name, ams.acs
            HAVING count(DISTINCT s.match_id) >= {MIN_AGENT_MATCHES} AND sum(s.score)::real / sum(s.rounds) > ams.acs
            ORDER BY s.player_id, sum(s.score)::real / sum(s.rounds) - ams.acs DESC"""
    ):
        title, body = t.best_agent(agent, map_name, acs, base, matches)
        insights.append(Insight("player", player, "agent", "positive", 1, title, body, matches,
                                min(1.0, matches / 10), map_id, metric_value=acs, baseline_value=base))
    for player, map_id, map_name, kd, own_kd, matches in conn.execute(
        f"""WITH per_map AS (
                SELECT player_id, map_id, sum(kills)::real / greatest(sum(deaths), 1) AS kd,
                       count(DISTINCT match_id) AS matches
                FROM analytics.player_match_stats GROUP BY 1, 2
            ), overall AS (
                SELECT player_id, sum(kills)::real / greatest(sum(deaths), 1) AS kd FROM analytics.player_match_stats GROUP BY 1
            )
            SELECT DISTINCT ON (p.player_id) p.player_id, p.map_id, m.name, p.kd, o.kd, p.matches
            FROM per_map p JOIN overall o USING (player_id) JOIN analytics.maps m ON m.id = p.map_id
            WHERE p.matches >= {MIN_MAP_MATCHES} AND p.kd > o.kd
            ORDER BY p.player_id, p.kd DESC"""
    ):
        title, body = t.best_map(map_name, kd, own_kd, matches)
        insights.append(Insight("player", player, "map", "positive", 1, title, body, matches,
                                min(1.0, matches / 10), map_id, metric_value=kd, baseline_value=own_kd))
    return insights


FALLBACK_METRICS = (
    ("acs", "pontuação por round (ACS)", "sum(score)::real / sum(rounds)", 0),
    ("adr", "dano por round (ADR)", "sum(damage)::real / sum(rounds)", 0),
    ("kast", "participação nos rounds (KAST)", "sum(kast_rounds)::real / sum(rounds)", -1),
    ("hs", "porcentagem de tiros na cabeça", "sum(headshots)::real / greatest(sum(headshots + bodyshots + legshots), 1)", -1),
    ("fk", "abates de abertura por round", "sum(first_kills)::real / sum(rounds)", 2),
)


def _fallback(conn: psycopg.Connection, covered: set[int]) -> list[Insight]:
    eligible = [
        row[0] for row in conn.execute(
            f"SELECT player_id FROM analytics.match_players GROUP BY 1 HAVING count(*) >= {MIN_PLAYER_MATCHES}"
        )
        if row[0] not in covered
    ]
    if not eligible:
        return []
    selects = ", ".join(f"{expr} AS {key}" for key, _, expr, _ in FALLBACK_METRICS)
    overall = conn.execute(f"SELECT {selects} FROM analytics.player_match_stats").fetchone()
    assert overall is not None
    insights = []
    for player, matches, *values in conn.execute(
        f"""SELECT player_id, count(DISTINCT match_id), {selects} FROM analytics.player_match_stats
            WHERE player_id = ANY(%s) GROUP BY 1""",
        (eligible,),
    ):
        index = max(range(len(values)), key=lambda i: values[i] / overall[i] if overall[i] else 0)
        key, label, _, decimals = FALLBACK_METRICS[index]
        value, base = values[index], overall[index]
        shown, shown_base = (
            (t.percent(value), t.percent(base)) if decimals == -1 else (t.number(value, decimals), t.number(base, decimals))
        )
        insights.append(Insight(
            "player", player, "summary", "positive", 1, "Seu melhor indicador",
            f"Seu ponto mais forte: {label}, com {shown}. A média dos jogadores é {shown_base}.",
            matches, min(1.0, matches / 10), metric_value=value, baseline_value=base,
        ))
    return insights


def build_insights(conn: psycopg.Connection) -> dict[str, int]:
    insights = (
        _patterns(conn) + _economy(conn) + _pressure(conn) + _rotations(conn)
        + _abilities(conn) + _strategies(conn) + _strengths(conn)
    )
    insights += _fallback(conn, {i.scope_id for i in insights if i.scope == "player"})
    with conn.transaction():
        conn.execute("TRUNCATE analytics.insights RESTART IDENTITY")
        with conn.cursor() as cur, cur.copy(
            """COPY analytics.insights (scope, scope_id, map_id, side, kind, polarity, severity, title, body,
                   metric_value, baseline_value, sample_size, confidence, is_estimate, evidence_round_ids) FROM STDIN"""
        ) as copy:
            for i in insights:
                copy.write_row((
                    i.scope, i.scope_id, i.map_id, i.side, i.kind, i.polarity, i.severity, i.title, i.body,
                    i.metric_value, i.baseline_value, i.sample_size, round(i.confidence, 3), i.is_estimate,
                    i.evidence,
                ))
        uncovered = conn.execute(
            f"""SELECT count(*) FROM (
                    SELECT player_id FROM analytics.match_players GROUP BY 1 HAVING count(*) >= {MIN_PLAYER_MATCHES}
                ) p
                WHERE NOT EXISTS (
                    SELECT 1 FROM analytics.insights i WHERE i.scope = 'player' AND i.scope_id = p.player_id
                )"""
        ).fetchone()
    counts = Counter(i.kind for i in insights)
    counts["jogadores_sem_insight"] = int(uncovered[0]) if uncovered else 0
    return dict(counts)
