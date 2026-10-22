SET search_path TO analytics;

CREATE TABLE pressure_stats (
    player_id       integer NOT NULL REFERENCES players(id),
    team_id         integer NOT NULL REFERENCES teams(id),
    map_id          smallint NOT NULL REFERENCES maps(id) ON DELETE CASCADE,
    stage_id        smallint NOT NULL REFERENCES stages(id),
    side            text NOT NULL CHECK (side IN ('attack', 'defense')),
    context         text NOT NULL,
    rounds          integer NOT NULL,
    rounds_won      integer NOT NULL,
    survived        integer NOT NULL,
    kills           integer NOT NULL,
    deaths          integer NOT NULL,
    wp_delta        real NOT NULL,
    PRIMARY KEY (player_id, team_id, map_id, stage_id, side, context)
);

CREATE TABLE rotations (
    round_id        bigint NOT NULL REFERENCES rounds(id) ON DELETE CASCADE,
    player_id       integer NOT NULL REFERENCES players(id),
    team_id         integer NOT NULL REFERENCES teams(id),
    map_id          smallint NOT NULL REFERENCES maps(id) ON DELETE CASCADE,
    side            text NOT NULL CHECK (side IN ('attack', 'defense')),
    from_region     text NOT NULL,
    to_region       text NOT NULL,
    left_after_ms   integer NOT NULL,
    seen_at_ms      integer NOT NULL,
    informed        boolean NOT NULL,
    source_fell     boolean NOT NULL,
    round_won       boolean NOT NULL,
    PRIMARY KEY (round_id, player_id, seen_at_ms)
);

CREATE INDEX ON pressure_stats (team_id);
CREATE INDEX ON pressure_stats (player_id);
CREATE INDEX ON rotations (team_id);
CREATE INDEX ON rotations (player_id);
