import psycopg

HEATMAP_GRID = 64

_CONTEXT = """
    SELECT r.id AS round_id, m.id AS match_id, m.map_id, s.stage_id
    FROM analytics.rounds r
    JOIN analytics.matches m ON m.id = r.match_id
    JOIN analytics.series s ON s.id = m.series_id
"""

_EVENTS = """
    SELECT ps.round_id, ps.player_id, ps.nx AS x, ps.ny AS y, {zone} AS zone_id,
           1 AS presence, 0 AS kills, 0 AS deaths, 0 AS first_kills, 0 AS first_deaths, 0 AS traded_deaths
    FROM analytics.position_samples ps
    WHERE ps.nx IS NOT NULL
    UNION ALL
    SELECT k.round_id, k.killer_id, k.killer_nx, k.killer_ny, {killer_zone},
           0, 1, 0, k.is_first_kill::int, 0, 0
    FROM analytics.kills k
    WHERE k.kind = 'enemy' AND k.killer_nx IS NOT NULL
    UNION ALL
    SELECT k.round_id, k.victim_id, k.victim_nx, k.victim_ny, {victim_zone},
           0, 0, 1, 0, k.is_first_kill::int, (k.traded_after_ms IS NOT NULL)::int
    FROM analytics.kills k
    WHERE k.kind = 'enemy' AND k.victim_nx IS NOT NULL
"""

_METRICS = """sum(e.presence), sum(e.kills), sum(e.deaths), sum(e.first_kills), sum(e.first_deaths), sum(e.traded_deaths)"""

_JOINS = """
    FROM events e
    JOIN ctx ON ctx.round_id = e.round_id
    JOIN analytics.round_players rp ON rp.round_id = e.round_id AND rp.player_id = e.player_id
    JOIN analytics.match_players mp ON mp.match_id = ctx.match_id AND mp.player_id = e.player_id
"""

CELLS_SQL = f"""
    INSERT INTO analytics.heatmap_cells (map_id, stage_id, team_id, player_id, agent_id, side, cx, cy,
        presence, kills, deaths, first_kills, first_deaths, traded_deaths)
    WITH ctx AS ({_CONTEXT}),
         events AS ({_EVENTS.format(zone="NULL::integer", killer_zone="NULL::integer", victim_zone="NULL::integer")})
    SELECT ctx.map_id, ctx.stage_id, rp.team_id, e.player_id, mp.agent_id, rp.side,
           least(greatest(floor(e.x * {HEATMAP_GRID}), 0), {HEATMAP_GRID - 1}) AS cx,
           least(greatest(floor(e.y * {HEATMAP_GRID}), 0), {HEATMAP_GRID - 1}) AS cy,
           {_METRICS}
    {_JOINS}
    GROUP BY 1, 2, 3, 4, 5, 6, 7, 8
"""

ZONES_SQL = f"""
    INSERT INTO analytics.heatmap_zones (map_id, stage_id, team_id, player_id, agent_id, side, zone_id,
        presence, kills, deaths, first_kills, first_deaths, traded_deaths)
    WITH ctx AS ({_CONTEXT}),
         events AS ({_EVENTS.format(zone="ps.zone_id", killer_zone="k.killer_zone_id", victim_zone="k.victim_zone_id")})
    SELECT ctx.map_id, ctx.stage_id, rp.team_id, e.player_id, mp.agent_id, rp.side, e.zone_id,
           {_METRICS}
    {_JOINS}
    WHERE e.zone_id IS NOT NULL
    GROUP BY 1, 2, 3, 4, 5, 6, 7
"""


def build_heatmaps(conn: psycopg.Connection) -> tuple[int, int]:
    with conn.transaction():
        conn.execute("TRUNCATE analytics.heatmap_cells, analytics.heatmap_zones")
        cells = conn.execute(CELLS_SQL).rowcount
        zones = conn.execute(ZONES_SQL).rowcount
    return cells, zones
