SET search_path TO analytics;

CREATE TABLE model_runs (
    id              integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    model           text NOT NULL,
    pipeline_version text NOT NULL,
    trained_at      timestamptz NOT NULL DEFAULT now(),
    seed            integer NOT NULL,
    params          jsonb NOT NULL,
    metrics         jsonb NOT NULL
);

CREATE TABLE round_wp_states (
    round_id        bigint NOT NULL REFERENCES rounds(id) ON DELETE CASCADE,
    seq             smallint NOT NULL,
    event           text NOT NULL CHECK (event IN ('start', 'pre_kill', 'kill', 'plant')),
    kill_id         bigint REFERENCES kills(id) ON DELETE CASCADE,
    t_round_ms      integer NOT NULL,
    attack_alive    smallint NOT NULL,
    defense_alive   smallint NOT NULL,
    wp_attack       real NOT NULL,
    PRIMARY KEY (round_id, seq)
);

CREATE TABLE kill_impact (
    kill_id         bigint PRIMARY KEY REFERENCES kills(id) ON DELETE CASCADE,
    round_id        bigint NOT NULL REFERENCES rounds(id) ON DELETE CASCADE,
    killer_id       integer REFERENCES players(id),
    victim_id       integer NOT NULL REFERENCES players(id),
    killer_side     text CHECK (killer_side IN ('attack', 'defense')),
    victim_side     text NOT NULL CHECK (victim_side IN ('attack', 'defense')),
    wp_before_attack real NOT NULL,
    wp_after_attack real NOT NULL,
    victim_delta    real NOT NULL
);

CREATE INDEX ON kill_impact (killer_id);
CREATE INDEX ON kill_impact (victim_id);
