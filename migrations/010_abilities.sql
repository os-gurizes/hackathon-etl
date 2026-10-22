SET search_path TO analytics;

CREATE TABLE ability_usage (
    match_id            integer NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    player_id           integer NOT NULL REFERENCES players(id),
    team_id             integer NOT NULL REFERENCES teams(id),
    agent_id            smallint NOT NULL REFERENCES agents(id),
    map_id              smallint NOT NULL REFERENCES maps(id),
    rounds              smallint NOT NULL,
    casts               integer NOT NULL,
    casts_per_round     real NOT NULL,
    casts_percentile    real NOT NULL,
    impact_per_round    real NOT NULL,
    impact_percentile   real NOT NULL,
    ability_kills       smallint NOT NULL,
    ult_casts           smallint NOT NULL,
    ult_kills           smallint NOT NULL,
    ult_kills_decided   smallint NOT NULL,
    likely_overuse      boolean NOT NULL,
    PRIMARY KEY (match_id, player_id)
);

CREATE TABLE ability_kills (
    match_id        integer NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    player_id       integer NOT NULL REFERENCES players(id),
    agent_id        smallint NOT NULL REFERENCES agents(id),
    slot            text NOT NULL,
    ability_name    text,
    kills           smallint NOT NULL,
    wp_gain         real NOT NULL,
    PRIMARY KEY (match_id, player_id, slot)
);

CREATE TABLE combos (
    team_id         integer NOT NULL REFERENCES teams(id),
    map_id          smallint NOT NULL REFERENCES maps(id) ON DELETE CASCADE,
    stage_id        smallint NOT NULL REFERENCES stages(id),
    side            text NOT NULL CHECK (side IN ('attack', 'defense')),
    kind            text NOT NULL CHECK (kind IN ('assist', 'ability_followup')),
    player_a        integer NOT NULL REFERENCES players(id),
    player_b        integer NOT NULL REFERENCES players(id),
    agent_a         smallint NOT NULL REFERENCES agents(id),
    agent_b         smallint NOT NULL REFERENCES agents(id),
    occurrences     integer NOT NULL,
    wp_gain         real NOT NULL,
    site_control    integer NOT NULL,
    rounds_won      integer NOT NULL,
    PRIMARY KEY (team_id, map_id, stage_id, side, kind, player_a, player_b, agent_a, agent_b)
);

CREATE INDEX ON ability_usage (player_id);
CREATE INDEX ON combos (team_id);
CREATE INDEX ON combos (agent_a, agent_b);
