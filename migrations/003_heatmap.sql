SET search_path TO analytics;

CREATE TABLE heatmap_cells (
    map_id          smallint NOT NULL REFERENCES maps(id) ON DELETE CASCADE,
    stage_id        smallint NOT NULL REFERENCES stages(id),
    team_id         integer NOT NULL REFERENCES teams(id),
    player_id       integer NOT NULL REFERENCES players(id),
    agent_id        smallint NOT NULL REFERENCES agents(id),
    side            text NOT NULL CHECK (side IN ('attack', 'defense')),
    cx              smallint NOT NULL,
    cy              smallint NOT NULL,
    presence        integer NOT NULL,
    kills           integer NOT NULL,
    deaths          integer NOT NULL,
    first_kills     integer NOT NULL,
    first_deaths    integer NOT NULL,
    traded_deaths   integer NOT NULL,
    PRIMARY KEY (map_id, stage_id, team_id, player_id, agent_id, side, cx, cy)
);

CREATE TABLE heatmap_zones (
    map_id          smallint NOT NULL REFERENCES maps(id) ON DELETE CASCADE,
    stage_id        smallint NOT NULL REFERENCES stages(id),
    team_id         integer NOT NULL REFERENCES teams(id),
    player_id       integer NOT NULL REFERENCES players(id),
    agent_id        smallint NOT NULL REFERENCES agents(id),
    side            text NOT NULL CHECK (side IN ('attack', 'defense')),
    zone_id         integer NOT NULL REFERENCES zones(id) ON DELETE CASCADE,
    presence        integer NOT NULL,
    kills           integer NOT NULL,
    deaths          integer NOT NULL,
    first_kills     integer NOT NULL,
    first_deaths    integer NOT NULL,
    traded_deaths   integer NOT NULL,
    PRIMARY KEY (map_id, stage_id, team_id, player_id, agent_id, side, zone_id)
);

CREATE INDEX ON heatmap_cells (map_id, side);
CREATE INDEX ON heatmap_cells (player_id);
CREATE INDEX ON heatmap_cells (team_id);
CREATE INDEX ON heatmap_zones (map_id, side);
CREATE INDEX ON heatmap_zones (player_id);
CREATE INDEX ON heatmap_zones (team_id);
