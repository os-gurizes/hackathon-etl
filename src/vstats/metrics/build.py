from collections import defaultdict

import psycopg

from vstats.metrics.rounds import KillEvent, round_player_stats

PRIOR_ROUNDS = 200
PRIOR_DEATHS = 140

PLAYER_MATCH_SQL = """
    INSERT INTO analytics.player_match_stats
    SELECT m.id, rp.player_id, rp.side, m.map_id, s.stage_id, rp.team_id, mp.agent_id,
           count(*), count(*) FILTER (WHERE r.winner_team_id = rp.team_id),
           sum(rp.score), sum(rs.kills), sum(rs.deaths), sum(rs.assists),
           sum(rp.damage_dealt), sum(rp.headshots), sum(rp.bodyshots), sum(rp.legshots),
           count(*) FILTER (WHERE rs.kast),
           count(*) FILTER (WHERE rs.first_kill), count(*) FILTER (WHERE rs.first_death),
           sum(rs.trade_kills), count(*) FILTER (WHERE rs.traded_death),
           count(*) FILTER (WHERE rs.kills = 2), count(*) FILTER (WHERE rs.kills = 3),
           count(*) FILTER (WHERE rs.kills = 4), count(*) FILTER (WHERE rs.kills >= 5),
           count(*) FILTER (WHERE rs.clutch_size IS NOT NULL), count(*) FILTER (WHERE rs.clutch_won),
           count(*) FILTER (WHERE r.planter_id = rp.player_id), count(*) FILTER (WHERE r.defuser_id = rp.player_id)
    FROM analytics.round_players rp
    JOIN analytics.round_player_stats rs ON rs.round_id = rp.round_id AND rs.player_id = rp.player_id
    JOIN analytics.rounds r ON r.id = rp.round_id
    JOIN analytics.matches m ON m.id = r.match_id
    JOIN analytics.series s ON s.id = m.series_id
    JOIN analytics.match_players mp ON mp.match_id = m.id AND mp.player_id = rp.player_id
    GROUP BY m.id, rp.player_id, rp.side, m.map_id, s.stage_id, rp.team_id, mp.agent_id
"""

WEAPON_SQL = """
    INSERT INTO analytics.weapon_stats
    WITH ctx AS (
        SELECT rp.round_id, rp.player_id, rp.side, rp.team_id, m.id AS match_id, m.map_id, s.stage_id,
               mp.agent_id, rp.weapon_id, (r.winner_team_id = rp.team_id) AS won,
               rp.damage_dealt, rp.headshots, rp.bodyshots, rp.legshots
        FROM analytics.round_players rp
        JOIN analytics.rounds r ON r.id = rp.round_id
        JOIN analytics.matches m ON m.id = r.match_id
        JOIN analytics.series s ON s.id = m.series_id
        JOIN analytics.match_players mp ON mp.match_id = m.id AND mp.player_id = rp.player_id
    ),
    equipped AS (
        SELECT match_id, player_id, side, weapon_id, map_id, stage_id, team_id, agent_id,
               count(*) AS rounds, count(*) FILTER (WHERE won) AS rounds_won,
               sum(damage_dealt) AS damage, sum(headshots) AS hs, sum(bodyshots) AS bs, sum(legshots) AS ls
        FROM ctx WHERE weapon_id IS NOT NULL
        GROUP BY 1, 2, 3, 4, 5, 6, 7, 8
    ),
    killed AS (
        SELECT ctx.match_id, ctx.player_id, ctx.side, k.weapon_id, ctx.map_id, ctx.stage_id, ctx.team_id, ctx.agent_id,
               count(*) AS kills, count(*) FILTER (WHERE k.is_first_kill) AS first_kills,
               count(*) FILTER (WHERE k.distance_m < 10) AS d0,
               count(*) FILTER (WHERE k.distance_m >= 10 AND k.distance_m < 20) AS d10,
               count(*) FILTER (WHERE k.distance_m >= 20 AND k.distance_m < 30) AS d20,
               count(*) FILTER (WHERE k.distance_m >= 30) AS d30,
               coalesce(sum(k.distance_m), 0) AS dist, count(k.distance_m) AS dist_n
        FROM analytics.kills k
        JOIN ctx ON ctx.round_id = k.round_id AND ctx.player_id = k.killer_id
        WHERE k.kind = 'enemy' AND k.weapon_id IS NOT NULL
        GROUP BY 1, 2, 3, 4, 5, 6, 7, 8
    )
    SELECT coalesce(e.match_id, k.match_id), coalesce(e.player_id, k.player_id), coalesce(e.side, k.side),
           coalesce(e.weapon_id, k.weapon_id), coalesce(e.map_id, k.map_id), coalesce(e.stage_id, k.stage_id),
           coalesce(e.team_id, k.team_id), coalesce(e.agent_id, k.agent_id),
           coalesce(e.rounds, 0), coalesce(e.rounds_won, 0), coalesce(e.damage, 0),
           coalesce(e.hs, 0), coalesce(e.bs, 0), coalesce(e.ls, 0),
           coalesce(k.kills, 0), coalesce(k.first_kills, 0),
           coalesce(k.d0, 0), coalesce(k.d10, 0), coalesce(k.d20, 0), coalesce(k.d30, 0),
           coalesce(k.dist, 0), coalesce(k.dist_n, 0)
    FROM equipped e
    FULL JOIN killed k USING (match_id, player_id, side, weapon_id)
"""

AGENT_MAP_SQL = f"""
    INSERT INTO analytics.agent_map_stats
    WITH per_agent AS (
        SELECT map_id, agent_id, count(DISTINCT (match_id, player_id)) AS picks,
               sum(rounds) AS rounds, sum(rounds_won) AS won, sum(score) AS score,
               sum(kills) AS kills, sum(deaths) AS deaths
        FROM analytics.player_match_stats GROUP BY 1, 2
    ),
    per_map AS (
        SELECT m.map_id, count(*) * 2 AS slots,
               (SELECT sum(score)::real / sum(rounds) FROM analytics.player_match_stats p WHERE p.map_id = m.map_id) AS acs,
               (SELECT sum(kills)::real / greatest(sum(deaths), 1) FROM analytics.player_match_stats p WHERE p.map_id = m.map_id) AS kd
        FROM analytics.matches m GROUP BY m.map_id
    )
    SELECT a.map_id, a.agent_id, a.picks, a.picks::real / pm.slots, a.rounds, a.won::real / a.rounds,
           a.score::real / a.rounds, a.kills::real / greatest(a.deaths, 1),
           (a.score + {PRIOR_ROUNDS} * pm.acs) / (a.rounds + {PRIOR_ROUNDS}),
           (a.kills + {PRIOR_DEATHS} * pm.kd) / (a.deaths + {PRIOR_DEATHS})
    FROM per_agent a JOIN per_map pm ON pm.map_id = a.map_id
"""


def _round_rows(conn: psycopg.Connection) -> list[tuple]:
    team_of: dict[int, dict[int, int]] = defaultdict(dict)
    for round_id, player_id, team_id in conn.execute(
        "SELECT round_id, player_id, team_id FROM analytics.round_players"
    ):
        team_of[round_id][player_id] = team_id
    winners: dict[int, int] = {}
    defused_at: dict[int, int | None] = {}
    for round_id, winner, defuse_time in conn.execute("SELECT id, winner_team_id, defuse_time_ms FROM analytics.rounds"):
        winners[round_id] = winner
        defused_at[round_id] = defuse_time
    assists: dict[int, list[int]] = defaultdict(list)
    for kill_id, player_id in conn.execute("SELECT kill_id, player_id FROM analytics.kill_assists"):
        assists[kill_id].append(player_id)
    kills: dict[int, list[KillEvent]] = defaultdict(list)
    for row in conn.execute(
        """SELECT id, round_id, seq, killer_id, victim_id, kind, damage_type, is_first_kill, is_trade,
                  traded_after_ms IS NOT NULL, t_round_ms
           FROM analytics.kills ORDER BY round_id, seq"""
    ):
        kill_id, round_id, *fields, t_round_ms = row
        kills[round_id].append(KillEvent(*fields, assistants=tuple(assists[kill_id]), t_round_ms=t_round_ms))

    rows = []
    for round_id, teams in team_of.items():
        for s in round_player_stats(teams, winners[round_id], kills[round_id], defused_at[round_id]):
            rows.append((
                round_id, s.player_id, s.kills, s.deaths, s.assists, s.kast, s.first_kill, s.first_death,
                s.trade_kills, s.traded_death, s.clutch_size, s.clutch_won,
            ))
    return rows


def build_stats(conn: psycopg.Connection) -> dict[str, int]:
    rows = _round_rows(conn)
    with conn.transaction():
        conn.execute(
            """TRUNCATE analytics.round_player_stats, analytics.player_match_stats,
                        analytics.weapon_stats, analytics.agent_map_stats"""
        )
        with conn.cursor() as cur, cur.copy(
            """COPY analytics.round_player_stats (round_id, player_id, kills, deaths, assists, kast, first_kill,
                   first_death, trade_kills, traded_death, clutch_size, clutch_won) FROM STDIN"""
        ) as copy:
            for row in rows:
                copy.write_row(row)
        return {
            "round_player_stats": len(rows),
            "player_match_stats": conn.execute(PLAYER_MATCH_SQL).rowcount,
            "weapon_stats": conn.execute(WEAPON_SQL).rowcount,
            "agent_map_stats": conn.execute(AGENT_MAP_SQL).rowcount,
        }
