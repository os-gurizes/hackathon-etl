SET search_path TO analytics;

CREATE TABLE round_team_economy (
    round_id        bigint NOT NULL REFERENCES rounds(id) ON DELETE CASCADE,
    team_id         integer NOT NULL REFERENCES teams(id),
    match_id        integer NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    map_id          smallint NOT NULL REFERENCES maps(id),
    stage_id        smallint NOT NULL REFERENCES stages(id),
    number          smallint NOT NULL,
    side            text NOT NULL CHECK (side IN ('attack', 'defense')),
    buy_type        text NOT NULL CHECK (buy_type IN ('pistol', 'eco', 'semi_eco', 'half_buy', 'full_buy')),
    opponent_buy    text NOT NULL,
    loadout         integer NOT NULL,
    spent           integer NOT NULL,
    bank            integer NOT NULL,
    damage          integer NOT NULL,
    won             boolean NOT NULL,
    expected_win    real NOT NULL,
    PRIMARY KEY (round_id, team_id)
);

CREATE TABLE economy_flags (
    round_id        bigint NOT NULL REFERENCES rounds(id) ON DELETE CASCADE,
    team_id         integer NOT NULL REFERENCES teams(id),
    player_id       integer REFERENCES players(id),
    flag            text NOT NULL,
    won             boolean NOT NULL,
    expected_win    real NOT NULL,
    detail          text NOT NULL
);

CREATE INDEX ON round_team_economy (team_id);
CREATE INDEX ON round_team_economy (map_id);
CREATE INDEX ON economy_flags (team_id, flag);
CREATE INDEX ON economy_flags (player_id);
