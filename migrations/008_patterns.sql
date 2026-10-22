SET search_path TO analytics;

CREATE TABLE player_patterns (
    player_id       integer NOT NULL REFERENCES players(id),
    map_id          smallint NOT NULL REFERENCES maps(id) ON DELETE CASCADE,
    side            text NOT NULL CHECK (side IN ('attack', 'defense')),
    pattern         text NOT NULL,
    zone_id         integer REFERENCES zones(id) ON DELETE CASCADE,
    rounds          integer NOT NULL,
    occurrences     integer NOT NULL,
    expected        real NOT NULL,
    rate            real NOT NULL,
    baseline_rate   real NOT NULL,
    p_value         real,
    p_adjusted      real,
    cost_rounds     real NOT NULL,
    significant     boolean NOT NULL,
    evidence_round_ids bigint[] NOT NULL
);

CREATE INDEX ON player_patterns (player_id);
CREATE INDEX ON player_patterns (map_id, side);
