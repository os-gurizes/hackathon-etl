CREATE SCHEMA IF NOT EXISTS analytics;
SET search_path TO analytics;

CREATE TABLE tournaments (
    id          smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    slug        text NOT NULL UNIQUE,
    name        text NOT NULL
);

CREATE TABLE stages (
    id              smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tournament_id   smallint NOT NULL REFERENCES tournaments(id),
    slug            text NOT NULL,
    name            text NOT NULL,
    sort_order      smallint NOT NULL,
    UNIQUE (tournament_id, slug)
);

CREATE TABLE teams (
    id              integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    slug            text NOT NULL UNIQUE,
    display_name    text NOT NULL
);

CREATE TABLE players (
    id              integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    puuid_hash      text NOT NULL UNIQUE,
    game_name       text NOT NULL,
    tag_line        text NOT NULL,
    last_seen_at    timestamptz NOT NULL
);

CREATE TABLE agents (
    id              smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    uuid            text NOT NULL UNIQUE,
    name            text NOT NULL,
    role            text,
    ability_grenade text,
    ability_1       text,
    ability_2       text,
    ultimate        text
);

CREATE TABLE weapons (
    id              smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    uuid            text NOT NULL UNIQUE,
    name            text NOT NULL,
    category        text,
    cost            integer,
    is_armor        boolean NOT NULL
);

CREATE TABLE maps (
    id              smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    internal_name   text NOT NULL UNIQUE,
    slug            text NOT NULL UNIQUE,
    name            text NOT NULL,
    x_mult          double precision,
    y_mult          double precision,
    x_add           double precision,
    y_add           double precision,
    silhouette_svg  text,
    bounds          jsonb
);

CREATE TABLE map_callouts (
    map_id          smallint NOT NULL REFERENCES maps(id) ON DELETE CASCADE,
    region          text NOT NULL,
    super_region    text NOT NULL,
    x               double precision NOT NULL,
    y               double precision NOT NULL,
    nx              double precision,
    ny              double precision,
    PRIMARY KEY (map_id, super_region, region)
);

CREATE TABLE series (
    id              integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    stage_id        smallint NOT NULL REFERENCES stages(id),
    number          smallint NOT NULL,
    team_a_id       integer NOT NULL REFERENCES teams(id),
    team_b_id       integer NOT NULL REFERENCES teams(id),
    winner_team_id  integer REFERENCES teams(id),
    UNIQUE (stage_id, number)
);

CREATE TABLE matches (
    id              integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    match_uuid      uuid NOT NULL UNIQUE,
    series_id       integer NOT NULL REFERENCES series(id),
    game_letter     text NOT NULL,
    map_id          smallint NOT NULL REFERENCES maps(id),
    game_version    text NOT NULL,
    played_on       date NOT NULL,
    started_at      timestamptz NOT NULL,
    duration_ms     integer NOT NULL,
    red_team_id     integer NOT NULL REFERENCES teams(id),
    blue_team_id    integer NOT NULL REFERENCES teams(id),
    winner_team_id  integer NOT NULL REFERENCES teams(id),
    red_score       smallint NOT NULL,
    blue_score      smallint NOT NULL,
    rounds_played   smallint NOT NULL,
    source_file     text NOT NULL
);

CREATE TABLE match_players (
    match_id        integer NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    player_id       integer NOT NULL REFERENCES players(id),
    team_id         integer NOT NULL REFERENCES teams(id),
    agent_id        smallint NOT NULL REFERENCES agents(id),
    first_side      text NOT NULL CHECK (first_side IN ('attack', 'defense')),
    score           integer NOT NULL,
    kills           smallint NOT NULL,
    deaths          smallint NOT NULL,
    assists         smallint NOT NULL,
    rounds_played   smallint NOT NULL,
    casts_grenade   smallint NOT NULL,
    casts_1         smallint NOT NULL,
    casts_2         smallint NOT NULL,
    casts_ult       smallint NOT NULL,
    PRIMARY KEY (match_id, player_id)
);

-- round id = match_id * 100 + number; kill id = round id * 100 + seq (máx. 36 rounds e 11 kills por round no dataset)
CREATE TABLE rounds (
    id              bigint PRIMARY KEY,
    match_id        integer NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    number          smallint NOT NULL,
    winner_team_id  integer NOT NULL REFERENCES teams(id),
    winner_side     text NOT NULL CHECK (winner_side IN ('attack', 'defense')),
    attack_team_id  integer NOT NULL REFERENCES teams(id),
    defense_team_id integer NOT NULL REFERENCES teams(id),
    result_code     text NOT NULL,
    ceremony        text,
    plant_site      text,
    plant_time_ms   integer,
    planter_id      integer REFERENCES players(id),
    plant_x         integer,
    plant_y         integer,
    defuser_id      integer REFERENCES players(id),
    defuse_time_ms  integer,
    UNIQUE (match_id, number)
);

CREATE TABLE round_players (
    round_id        bigint NOT NULL REFERENCES rounds(id) ON DELETE CASCADE,
    player_id       integer NOT NULL REFERENCES players(id),
    team_id         integer NOT NULL REFERENCES teams(id),
    side            text NOT NULL CHECK (side IN ('attack', 'defense')),
    score           integer NOT NULL,
    loadout_value   integer NOT NULL,
    spent           integer NOT NULL,
    remaining       integer NOT NULL,
    weapon_id       smallint REFERENCES weapons(id),
    armor_id        smallint REFERENCES weapons(id),
    damage_dealt    integer NOT NULL,
    headshots       smallint NOT NULL,
    bodyshots       smallint NOT NULL,
    legshots        smallint NOT NULL,
    kills           smallint NOT NULL,
    died            boolean NOT NULL,
    PRIMARY KEY (round_id, player_id)
);

CREATE TABLE kills (
    id                  bigint PRIMARY KEY,
    round_id            bigint NOT NULL REFERENCES rounds(id) ON DELETE CASCADE,
    seq                 smallint NOT NULL,
    t_round_ms          integer NOT NULL,
    t_game_ms           integer NOT NULL,
    killer_id           integer REFERENCES players(id),
    victim_id           integer NOT NULL REFERENCES players(id),
    kind                text NOT NULL CHECK (kind IN ('enemy', 'team', 'self')),
    damage_type         text NOT NULL,
    weapon_id           smallint REFERENCES weapons(id),
    ability_slot        text,
    is_secondary_fire   boolean NOT NULL,
    killer_x            integer,
    killer_y            integer,
    victim_x            integer NOT NULL,
    victim_y            integer NOT NULL,
    distance_m          real,
    is_first_kill       boolean NOT NULL,
    is_trade            boolean NOT NULL,
    traded_after_ms     integer,
    UNIQUE (round_id, seq)
);

CREATE TABLE kill_assists (
    kill_id         bigint NOT NULL REFERENCES kills(id) ON DELETE CASCADE,
    player_id       integer NOT NULL REFERENCES players(id),
    PRIMARY KEY (kill_id, player_id)
);

CREATE TABLE damage_events (
    round_id        bigint NOT NULL REFERENCES rounds(id) ON DELETE CASCADE,
    dealer_id       integer NOT NULL REFERENCES players(id),
    receiver_id     integer NOT NULL REFERENCES players(id),
    damage          integer NOT NULL,
    headshots       smallint NOT NULL,
    bodyshots       smallint NOT NULL,
    legshots        smallint NOT NULL,
    PRIMARY KEY (round_id, dealer_id, receiver_id)
);

CREATE TABLE position_samples (
    kill_id         bigint NOT NULL REFERENCES kills(id) ON DELETE CASCADE,
    round_id        bigint NOT NULL,
    t_round_ms      integer NOT NULL,
    player_id       integer NOT NULL REFERENCES players(id),
    side            text NOT NULL CHECK (side IN ('attack', 'defense')),
    x               integer NOT NULL,
    y               integer NOT NULL,
    nx              real,
    ny              real,
    view_rad        real NOT NULL,
    zone_id         integer,
    PRIMARY KEY (kill_id, player_id)
);

CREATE TABLE ingest_runs (
    id              integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    started_at      timestamptz NOT NULL DEFAULT now(),
    finished_at     timestamptz,
    source          text NOT NULL,
    files_seen      integer NOT NULL DEFAULT 0,
    files_loaded    integer NOT NULL DEFAULT 0,
    files_skipped   integer NOT NULL DEFAULT 0,
    pipeline_version text NOT NULL
);

CREATE TABLE data_quality_report (
    run_id          integer NOT NULL REFERENCES ingest_runs(id) ON DELETE CASCADE,
    severity        text NOT NULL CHECK (severity IN ('info', 'warning', 'error')),
    code            text NOT NULL,
    source_file     text,
    detail          text NOT NULL
);

CREATE INDEX ON matches (series_id);
CREATE INDEX ON matches (map_id);
CREATE INDEX ON match_players (player_id);
CREATE INDEX ON match_players (team_id);
CREATE INDEX ON rounds (match_id);
CREATE INDEX ON round_players (player_id);
CREATE INDEX ON kills (round_id);
CREATE INDEX ON kills (killer_id);
CREATE INDEX ON kills (victim_id);
CREATE INDEX ON position_samples (round_id);
CREATE INDEX ON position_samples (player_id);
