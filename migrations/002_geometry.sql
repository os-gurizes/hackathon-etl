SET search_path TO analytics;

ALTER TABLE maps
    ADD COLUMN calibration text NOT NULL DEFAULT 'reference' CHECK (calibration IN ('reference', 'derived')),
    ADD COLUMN silhouette_quality text CHECK (silhouette_quality IN ('ok', 'low'));

CREATE TABLE map_sites (
    map_id          smallint NOT NULL REFERENCES maps(id) ON DELETE CASCADE,
    site            text NOT NULL,
    nx              real NOT NULL,
    ny              real NOT NULL,
    plants          integer NOT NULL,
    PRIMARY KEY (map_id, site)
);

CREATE TABLE zones (
    id              integer PRIMARY KEY,
    map_id          smallint NOT NULL REFERENCES maps(id) ON DELETE CASCADE,
    name            text NOT NULL,
    region          text NOT NULL,
    super_region    text NOT NULL,
    source          text NOT NULL CHECK (source IN ('callout', 'cluster')),
    anchor_nx       real NOT NULL,
    anchor_ny       real NOT NULL,
    label_nx        real NOT NULL,
    label_ny        real NOT NULL,
    area            real NOT NULL,
    path_svg        text NOT NULL
);

CREATE INDEX ON zones (map_id);

ALTER TABLE kills
    ADD COLUMN killer_nx real,
    ADD COLUMN killer_ny real,
    ADD COLUMN victim_nx real,
    ADD COLUMN victim_ny real,
    ADD COLUMN killer_zone_id integer REFERENCES zones(id) ON DELETE SET NULL,
    ADD COLUMN victim_zone_id integer REFERENCES zones(id) ON DELETE SET NULL;

ALTER TABLE rounds
    ADD COLUMN plant_nx real,
    ADD COLUMN plant_ny real,
    ADD COLUMN plant_zone_id integer REFERENCES zones(id) ON DELETE SET NULL;

ALTER TABLE position_samples
    ADD CONSTRAINT position_samples_zone_fk FOREIGN KEY (zone_id) REFERENCES zones(id) ON DELETE SET NULL;

CREATE INDEX ON position_samples (zone_id);
CREATE INDEX ON kills (killer_zone_id);
CREATE INDEX ON kills (victim_zone_id);
