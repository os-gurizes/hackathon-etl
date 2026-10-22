SET search_path TO analytics;

CREATE TABLE strategies (
    id              integer PRIMARY KEY,
    map_id          smallint NOT NULL REFERENCES maps(id) ON DELETE CASCADE,
    side            text NOT NULL CHECK (side IN ('attack', 'defense')),
    is_noise        boolean NOT NULL,
    title           text NOT NULL,
    description     text NOT NULL,
    rounds          integer NOT NULL,
    wins            integer NOT NULL,
    win_rate        real NOT NULL,
    ci_low          real NOT NULL,
    ci_high         real NOT NULL,
    region_counts   jsonb NOT NULL,
    top_zones       jsonb NOT NULL,
    plant_sites     jsonb NOT NULL,
    plant_time_s    real
);

CREATE TABLE round_strategy (
    round_id        bigint NOT NULL REFERENCES rounds(id) ON DELETE CASCADE,
    team_id         integer NOT NULL REFERENCES teams(id),
    side            text NOT NULL CHECK (side IN ('attack', 'defense')),
    strategy_id     integer NOT NULL REFERENCES strategies(id) ON DELETE CASCADE,
    confidence      real NOT NULL,
    won             boolean NOT NULL,
    PRIMARY KEY (round_id, team_id)
);

CREATE INDEX ON round_strategy (team_id, strategy_id);
CREATE INDEX ON round_strategy (strategy_id);
