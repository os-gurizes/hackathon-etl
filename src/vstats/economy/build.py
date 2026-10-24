import psycopg

PISTOL_ROUNDS = (0, 12)
ECO_BELOW = 6_000
SEMI_ECO_BELOW = 12_000
HALF_BUY_BELOW = 20_000
PLAYER_ECO_BELOW = 1_600
PLAYER_FULL_FROM = 3_700
CAN_DROP_FROM = 3_000
FORCE_FROM = 12_000
HALF_ROUNDS_END = (11, 23)
ECO_DAMAGE_BELOW = 250
MIN_MATRIX_CELL = 10
OVERTIME_FROM = 24

BUY_TYPE = f"""
    CASE
        WHEN r.number IN {PISTOL_ROUNDS} THEN 'pistol'
        WHEN sum(rp.loadout_value) < {ECO_BELOW} THEN 'eco'
        WHEN sum(rp.loadout_value) < {SEMI_ECO_BELOW} THEN 'semi_eco'
        WHEN sum(rp.loadout_value) < {HALF_BUY_BELOW} THEN 'half_buy'
        ELSE 'full_buy'
    END
"""

TEAM_ECONOMY_SQL = f"""
    INSERT INTO analytics.round_team_economy
    WITH team_round AS (
        SELECT r.id AS round_id, rp.team_id, m.id AS match_id, m.map_id, s.stage_id, r.number, min(rp.side) AS side,
               {BUY_TYPE} AS buy_type,
               sum(rp.loadout_value) AS loadout, sum(rp.spent) AS spent, sum(rp.remaining) AS bank,
               sum(rp.damage_dealt) AS damage, bool_and(r.winner_team_id = rp.team_id) AS won
        FROM analytics.round_players rp
        JOIN analytics.rounds r ON r.id = rp.round_id
        JOIN analytics.matches m ON m.id = r.match_id
        JOIN analytics.series s ON s.id = m.series_id
        GROUP BY r.id, rp.team_id, m.id, m.map_id, s.stage_id, r.number
    ),
    paired AS (
        SELECT t.*, o.buy_type AS opponent_buy
        FROM team_round t JOIN team_round o ON o.round_id = t.round_id AND o.team_id <> t.team_id
    ),
    matrix AS (
        SELECT buy_type, opponent_buy, sum(won::int) AS wins, count(*) AS n FROM paired GROUP BY 1, 2
    ),
    marginal AS (
        SELECT buy_type, sum(won::int) AS wins, count(*) AS n FROM paired GROUP BY 1
    )
    SELECT p.round_id, p.team_id, p.match_id, p.map_id, p.stage_id, p.number, p.side, p.buy_type, p.opponent_buy,
           p.loadout, p.spent, p.bank, p.damage, p.won,
           CASE WHEN x.n - 1 >= {MIN_MATRIX_CELL} THEN (x.wins - p.won::int)::real / (x.n - 1)
                ELSE (mg.wins - p.won::int)::real / greatest(mg.n - 1, 1)
           END
    FROM paired p
    JOIN matrix x USING (buy_type, opponent_buy)
    JOIN marginal mg USING (buy_type)
"""

FLAGS_SQL = f"""
    INSERT INTO analytics.economy_flags (round_id, team_id, player_id, flag, won, expected_win, detail)
    WITH previous AS (
        SELECT e.*, lag(e.won) OVER w AS prev_won, lag(e.number) OVER w AS prev_number,
               lead(e.buy_type) OVER w AS next_buy, lead(e.opponent_buy) OVER w AS next_opponent_buy,
               lead(e.won) OVER w AS next_won, lead(e.number) OVER w AS next_number,
               lead(e.expected_win) OVER w AS next_expected
        FROM analytics.round_team_economy e
        WINDOW w AS (PARTITION BY e.match_id, e.team_id ORDER BY e.number)
    ),
    regulation AS (
        SELECT * FROM analytics.round_team_economy WHERE number < {OVERTIME_FROM}
    ),
    players AS (
        SELECT rp.round_id, rp.team_id, rp.player_id, rp.loadout_value, rp.remaining, e.buy_type, e.won, e.expected_win
        FROM analytics.round_players rp
        JOIN regulation e ON e.round_id = rp.round_id AND e.team_id = rp.team_id
    )
    SELECT round_id, team_id, NULL::integer, 'force_after_pistol_loss', won, expected_win,
           'Forçou a compra (' || loadout || ') depois de perder o pistol'
    FROM previous
    WHERE prev_number IN {PISTOL_ROUNDS} AND prev_won = false AND loadout >= {FORCE_FROM}
    UNION ALL
    SELECT p.round_id, p.team_id, NULL, 'broken_economy', p.next_won, p.next_expected,
           'Perdeu a meia compra e jogou o round seguinte em ' || p.next_buy
    FROM previous p
    WHERE p.buy_type = 'half_buy' AND NOT p.won AND p.next_buy IN ('eco', 'semi_eco')
      AND p.next_number = p.number + 1 AND p.number NOT IN {HALF_ROUNDS_END} AND p.number < {OVERTIME_FROM} - 1
    UNION ALL
    SELECT round_id, team_id, NULL, 'eco_without_damage', won, expected_win,
           'Eco com apenas ' || damage || ' de dano do time'
    FROM regulation
    WHERE buy_type = 'eco' AND damage < {ECO_DAMAGE_BELOW}
    UNION ALL
    SELECT round_id, team_id, NULL, 'full_buy_lost_to_eco', won, expected_win,
           'Perdeu com compra completa contra eco do adversário'
    FROM regulation
    WHERE buy_type = 'full_buy' AND opponent_buy = 'eco' AND NOT won
    UNION ALL
    SELECT round_id, team_id, player_id, 'buy_out_of_sync', won, expected_win,
           'Comprou completo (' || loadout_value || ') com o time em ' || buy_type
    FROM players
    WHERE buy_type IN ('eco', 'semi_eco') AND loadout_value >= {PLAYER_FULL_FROM}
    UNION ALL
    SELECT round_id, team_id, player_id, 'saved_while_team_bought', won, expected_win,
           'Ficou com ' || loadout_value || ' de loadout e ' || remaining || ' guardados com o time comprando completo'
    FROM players
    WHERE buy_type = 'full_buy' AND loadout_value < {PLAYER_ECO_BELOW} AND remaining >= {PLAYER_FULL_FROM}
    UNION ALL
    SELECT p.round_id, p.team_id, p.player_id, 'did_not_drop', p.won, p.expected_win,
           'Sobraram ' || p.remaining || ' enquanto um aliado jogou com ' || min(mate.loadout_value)
    FROM players p
    JOIN players mate ON mate.round_id = p.round_id AND mate.team_id = p.team_id AND mate.player_id <> p.player_id
    WHERE p.buy_type IN ('half_buy', 'full_buy') AND p.loadout_value >= {PLAYER_FULL_FROM}
      AND p.remaining >= {CAN_DROP_FROM} AND mate.loadout_value < {PLAYER_ECO_BELOW} AND mate.remaining < 1000
    GROUP BY p.round_id, p.team_id, p.player_id, p.won, p.expected_win, p.remaining
"""


def build_economy(conn: psycopg.Connection) -> dict[str, int]:
    with conn.transaction():
        conn.execute("TRUNCATE analytics.round_team_economy, analytics.economy_flags")
        return {
            "round_team_economy": conn.execute(TEAM_ECONOMY_SQL).rowcount,
            "economy_flags": conn.execute(FLAGS_SQL).rowcount,
        }
