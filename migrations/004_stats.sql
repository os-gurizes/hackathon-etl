SET search_path TO analytics;

CREATE TABLE round_player_stats (
    round_id        bigint NOT NULL REFERENCES rounds(id) ON DELETE CASCADE,
    player_id       integer NOT NULL REFERENCES players(id),
    kills           smallint NOT NULL,
    deaths          smallint NOT NULL,
    assists         smallint NOT NULL,
    kast            boolean NOT NULL,
    first_kill      boolean NOT NULL,
    first_death     boolean NOT NULL,
    trade_kills     smallint NOT NULL,
    traded_death    boolean NOT NULL,
    clutch_size     smallint,
    clutch_won      boolean,
    PRIMARY KEY (round_id, player_id)
);

CREATE TABLE player_match_stats (
    match_id        integer NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    player_id       integer NOT NULL REFERENCES players(id),
    side            text NOT NULL CHECK (side IN ('attack', 'defense')),
    map_id          smallint NOT NULL REFERENCES maps(id),
    stage_id        smallint NOT NULL REFERENCES stages(id),
    team_id         integer NOT NULL REFERENCES teams(id),
    agent_id        smallint NOT NULL REFERENCES agents(id),
    rounds          smallint NOT NULL,
    rounds_won      smallint NOT NULL,
    score           integer NOT NULL,
    kills           smallint NOT NULL,
    deaths          smallint NOT NULL,
    assists         smallint NOT NULL,
    damage          integer NOT NULL,
    headshots       integer NOT NULL,
    bodyshots       integer NOT NULL,
    legshots        integer NOT NULL,
    kast_rounds     smallint NOT NULL,
    first_kills     smallint NOT NULL,
    first_deaths    smallint NOT NULL,
    trade_kills     smallint NOT NULL,
    traded_deaths   smallint NOT NULL,
    multikills_2    smallint NOT NULL,
    multikills_3    smallint NOT NULL,
    multikills_4    smallint NOT NULL,
    multikills_5    smallint NOT NULL,
    clutch_attempts smallint NOT NULL,
    clutch_wins     smallint NOT NULL,
    plants          smallint NOT NULL,
    defuses         smallint NOT NULL,
    PRIMARY KEY (match_id, player_id, side)
);

CREATE TABLE weapon_stats (
    match_id            integer NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    player_id           integer NOT NULL REFERENCES players(id),
    side                text NOT NULL CHECK (side IN ('attack', 'defense')),
    weapon_id           smallint NOT NULL REFERENCES weapons(id),
    map_id              smallint NOT NULL REFERENCES maps(id),
    stage_id            smallint NOT NULL REFERENCES stages(id),
    team_id             integer NOT NULL REFERENCES teams(id),
    agent_id            smallint NOT NULL REFERENCES agents(id),
    rounds_equipped     smallint NOT NULL,
    rounds_won_equipped smallint NOT NULL,
    damage_equipped     integer NOT NULL,
    headshots_equipped  integer NOT NULL,
    bodyshots_equipped  integer NOT NULL,
    legshots_equipped   integer NOT NULL,
    kills               smallint NOT NULL,
    first_kills         smallint NOT NULL,
    kills_0_10m         smallint NOT NULL,
    kills_10_20m        smallint NOT NULL,
    kills_20_30m        smallint NOT NULL,
    kills_30m_plus      smallint NOT NULL,
    distance_sum_m      real NOT NULL,
    distance_samples    smallint NOT NULL,
    PRIMARY KEY (match_id, player_id, side, weapon_id)
);

CREATE TABLE agent_map_stats (
    map_id          smallint NOT NULL REFERENCES maps(id),
    agent_id        smallint NOT NULL REFERENCES agents(id),
    picks           integer NOT NULL,
    pick_rate       real NOT NULL,
    rounds          integer NOT NULL,
    win_rate        real NOT NULL,
    acs             real NOT NULL,
    kd              real NOT NULL,
    acs_bayes       real NOT NULL,
    kd_bayes        real NOT NULL,
    PRIMARY KEY (map_id, agent_id)
);

CREATE INDEX ON player_match_stats (player_id);
CREATE INDEX ON player_match_stats (team_id);
CREATE INDEX ON player_match_stats (map_id, agent_id);
CREATE INDEX ON weapon_stats (weapon_id);
CREATE INDEX ON weapon_stats (player_id);
