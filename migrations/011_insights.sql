SET search_path TO analytics;

CREATE TABLE insights (
    id                  integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    scope               text NOT NULL CHECK (scope IN ('player', 'team')),
    scope_id            integer NOT NULL,
    map_id              smallint REFERENCES maps(id) ON DELETE CASCADE,
    side                text CHECK (side IN ('attack', 'defense')),
    kind                text NOT NULL,
    polarity            text NOT NULL CHECK (polarity IN ('negative', 'positive', 'neutral')),
    severity            smallint NOT NULL CHECK (severity BETWEEN 1 AND 3),
    title               text NOT NULL,
    body                text NOT NULL,
    metric_value        real,
    baseline_value      real,
    sample_size         integer NOT NULL,
    confidence          real NOT NULL,
    is_estimate         boolean NOT NULL,
    evidence_round_ids  bigint[] NOT NULL DEFAULT '{}'
);

CREATE INDEX ON insights (scope, scope_id);
CREATE INDEX ON insights (kind);
