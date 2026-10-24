import psycopg

OVERUSE_CASTS_PERCENTILE = 0.8
OVERUSE_IMPACT_PERCENTILE = 0.5
DECIDED_ABOVE = 0.85
DECIDED_BELOW = 0.10
FOLLOWUP_WINDOW_MS = 3_000

ABILITY_KILLS_SQL = """
    INSERT INTO analytics.ability_kills
    SELECT r.match_id, k.killer_id, mp.agent_id, k.ability_slot,
           CASE k.ability_slot
               WHEN 'Ultimate' THEN a.ultimate WHEN 'Ability1' THEN a.ability_1
               WHEN 'Ability2' THEN a.ability_2 WHEN 'GrenadeAbility' THEN a.ability_grenade
           END,
           count(*), coalesce(sum(-ki.victim_delta), 0)
    FROM analytics.kills k
    JOIN analytics.rounds r ON r.id = k.round_id
    JOIN analytics.match_players mp ON mp.match_id = r.match_id AND mp.player_id = k.killer_id
    JOIN analytics.agents a ON a.id = mp.agent_id
    LEFT JOIN analytics.kill_impact ki ON ki.kill_id = k.id
    WHERE k.kind = 'enemy' AND k.damage_type = 'Ability' AND k.ability_slot IS NOT NULL
    GROUP BY 1, 2, 3, 4, 5
"""

USAGE_SQL = f"""
    INSERT INTO analytics.ability_usage
    WITH base AS (
        SELECT mp.match_id, mp.player_id, mp.team_id, mp.agent_id, m.map_id, mp.rounds_played AS rounds,
               mp.casts_grenade + mp.casts_1 + mp.casts_2 AS casts, mp.casts_ult,
               (mp.kills + mp.assists)::real / greatest(mp.rounds_played, 1) AS impact_per_round
        FROM analytics.match_players mp
        JOIN analytics.matches m ON m.id = mp.match_id
    ),
    ult AS (
        SELECT r.match_id, k.killer_id AS player_id, count(*) AS kills,
               count(*) FILTER (WHERE
                   CASE WHEN ki.killer_side = 'attack' THEN ki.wp_before_attack ELSE 1 - ki.wp_before_attack END
                   NOT BETWEEN {DECIDED_BELOW} AND {DECIDED_ABOVE}) AS decided
        FROM analytics.kills k
        JOIN analytics.rounds r ON r.id = k.round_id
        JOIN analytics.kill_impact ki ON ki.kill_id = k.id
        WHERE k.kind = 'enemy' AND k.ability_slot = 'Ultimate'
        GROUP BY 1, 2
    ),
    ability AS (
        SELECT match_id, player_id, sum(kills) AS kills FROM analytics.ability_kills GROUP BY 1, 2
    ),
    ranked AS (
        SELECT b.*,
               b.casts::real / greatest(b.rounds, 1) AS casts_per_round,
               percent_rank() OVER (PARTITION BY b.map_id, b.agent_id ORDER BY b.casts::real / greatest(b.rounds, 1)) AS casts_pct,
               percent_rank() OVER (PARTITION BY b.map_id, b.agent_id ORDER BY b.impact_per_round) AS impact_pct
        FROM base b
    )
    SELECT r.match_id, r.player_id, r.team_id, r.agent_id, r.map_id, r.rounds, r.casts, r.casts_per_round,
           r.casts_pct, r.impact_per_round, r.impact_pct, coalesce(a.kills, 0), r.casts_ult,
           coalesce(u.kills, 0), coalesce(u.decided, 0),
           r.casts_pct >= {OVERUSE_CASTS_PERCENTILE} AND r.impact_pct <= {OVERUSE_IMPACT_PERCENTILE}
    FROM ranked r
    LEFT JOIN ult u USING (match_id, player_id)
    LEFT JOIN ability a USING (match_id, player_id)
"""

COMBOS_SQL = f"""
    INSERT INTO analytics.combos
    WITH ctx AS (
        SELECT k.id AS kill_id, k.round_id, k.t_round_ms, k.killer_id, k.damage_type, r.match_id, m.map_id,
               s.stage_id, rp.team_id, rp.side, mp.agent_id, coalesce(-ki.victim_delta, 0) AS wp_gain,
               (r.winner_team_id = rp.team_id) AS won,
               CASE WHEN rp.side = 'attack'
                    THEN coalesce(r.plant_time_ms > k.t_round_ms, false)
                         OR (r.plant_time_ms <= k.t_round_ms AND r.winner_team_id = rp.team_id)
                    ELSE r.winner_team_id = rp.team_id AND (r.plant_time_ms IS NULL OR r.defuser_id IS NOT NULL)
               END AS site_control
        FROM analytics.kills k
        JOIN analytics.rounds r ON r.id = k.round_id
        JOIN analytics.matches m ON m.id = r.match_id
        JOIN analytics.series s ON s.id = m.series_id
        JOIN analytics.round_players rp ON rp.round_id = k.round_id AND rp.player_id = k.killer_id
        JOIN analytics.match_players mp ON mp.match_id = r.match_id AND mp.player_id = k.killer_id
        LEFT JOIN analytics.kill_impact ki ON ki.kill_id = k.id
        WHERE k.kind = 'enemy'
    ),
    assist_pairs AS (
        SELECT c.team_id, c.map_id, c.stage_id, c.side, 'assist' AS kind, ka.player_id AS player_a,
               c.killer_id AS player_b, mpa.agent_id AS agent_a, c.agent_id AS agent_b,
               c.wp_gain, c.site_control, c.won
        FROM ctx c
        JOIN analytics.kill_assists ka ON ka.kill_id = c.kill_id
        JOIN analytics.match_players mpa ON mpa.match_id = c.match_id AND mpa.player_id = ka.player_id
        WHERE mpa.team_id = c.team_id
    ),
    followups AS (
        SELECT DISTINCT ON (a.killer_id, b.kill_id) b.team_id, b.map_id, b.stage_id, b.side, 'ability_followup' AS kind, a.killer_id AS player_a,
               b.killer_id AS player_b, a.agent_id AS agent_a, b.agent_id AS agent_b,
               b.wp_gain, b.site_control, b.won
        FROM ctx a
        JOIN ctx b ON b.round_id = a.round_id AND b.team_id = a.team_id AND b.killer_id <> a.killer_id
                  AND b.t_round_ms > a.t_round_ms AND b.t_round_ms - a.t_round_ms <= {FOLLOWUP_WINDOW_MS}
        WHERE a.damage_type = 'Ability'
        ORDER BY a.killer_id, b.kill_id
    )
    SELECT team_id, map_id, stage_id, side, kind, player_a, player_b, agent_a, agent_b,
           count(*), sum(wp_gain), count(*) FILTER (WHERE site_control), count(*) FILTER (WHERE won)
    FROM (SELECT * FROM assist_pairs UNION ALL SELECT * FROM followups) pairs
    GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9
"""


def build_abilities(conn: psycopg.Connection) -> dict[str, int]:
    with conn.transaction():
        conn.execute("TRUNCATE analytics.ability_usage, analytics.ability_kills, analytics.combos")
        return {
            "ability_kills": conn.execute(ABILITY_KILLS_SQL).rowcount,
            "ability_usage": conn.execute(USAGE_SQL).rowcount,
            "combos": conn.execute(COMBOS_SQL).rowcount,
        }
