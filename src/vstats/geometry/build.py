import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import psycopg
from numpy.typing import NDArray

from vstats.geometry.silhouette import SVG_SCALE, build_silhouette
from vstats.geometry.zones import (
    Anchor,
    Zone,
    ZoneIndex,
    build_zones,
    cluster_anchors,
    merge_duplicate_anchors,
    site_centroids,
)
from vstats.reference.resolver import REFERENCE_DIR

ZONE_LABELS_FILE = "zone-labels.json"

BY_MAP = """JOIN analytics.rounds r ON r.id = t.round_id
            JOIN analytics.matches m ON m.id = r.match_id
            WHERE m.map_id = %s"""

ROUNDS_BY_MAP = """FROM analytics.rounds r
                   JOIN analytics.matches m ON m.id = r.match_id
                   WHERE m.map_id = %s"""

ZONE_TARGETS = (
    (
        f"SELECT t.kill_id, t.player_id, t.nx, t.ny FROM analytics.position_samples t {BY_MAP}",
        """UPDATE analytics.position_samples t SET zone_id = z.zone_id FROM zone_assign z
           WHERE t.kill_id = z.k1 AND t.player_id = z.k2""",
    ),
    (
        f"SELECT t.id, 0, t.victim_nx, t.victim_ny FROM analytics.kills t {BY_MAP}",
        "UPDATE analytics.kills t SET victim_zone_id = z.zone_id FROM zone_assign z WHERE t.id = z.k1",
    ),
    (
        f"SELECT t.id, 0, t.killer_nx, t.killer_ny FROM analytics.kills t {BY_MAP} AND t.killer_nx IS NOT NULL",
        "UPDATE analytics.kills t SET killer_zone_id = z.zone_id FROM zone_assign z WHERE t.id = z.k1",
    ),
    (
        f"SELECT r.id, 0, r.plant_nx, r.plant_ny {ROUNDS_BY_MAP} AND r.plant_nx IS NOT NULL",
        "UPDATE analytics.rounds t SET plant_zone_id = z.zone_id FROM zone_assign z WHERE t.id = z.k1",
    ),
)

NORMALIZE = (
    """UPDATE analytics.position_samples t
        SET nx = t.y * mp.x_mult + mp.x_add, ny = t.x * mp.y_mult + mp.y_add
        FROM analytics.rounds r, analytics.matches m, analytics.maps mp
        WHERE r.id = t.round_id AND m.id = r.match_id AND mp.id = m.map_id AND mp.id = %s""",
    """UPDATE analytics.kills t
       SET killer_nx = t.killer_y * mp.x_mult + mp.x_add, killer_ny = t.killer_x * mp.y_mult + mp.y_add,
           victim_nx = t.victim_y * mp.x_mult + mp.x_add, victim_ny = t.victim_x * mp.y_mult + mp.y_add
       FROM analytics.rounds r, analytics.matches m, analytics.maps mp
       WHERE r.id = t.round_id AND m.id = r.match_id AND mp.id = m.map_id AND mp.id = %s""",
    """UPDATE analytics.rounds t
       SET plant_nx = t.plant_y * mp.x_mult + mp.x_add, plant_ny = t.plant_x * mp.y_mult + mp.y_add
       FROM analytics.matches m, analytics.maps mp
       WHERE m.id = t.match_id AND mp.id = m.map_id AND mp.id = %s AND t.plant_x IS NOT NULL""",
    """UPDATE analytics.map_callouts t
       SET nx = t.y * mp.x_mult + mp.x_add, ny = t.x * mp.y_mult + mp.y_add
       FROM analytics.maps mp WHERE mp.id = t.map_id AND mp.id = %s""",
)


@dataclass(frozen=True, slots=True)
class MapGeometry:
    map_id: int
    name: str
    sample_size: int
    quality: str
    zones: int
    zone_source: str
    sites: tuple[str, ...]


def zone_label(region: str, super_region: str) -> str:
    if super_region == "Meio":
        return f"{region} do Meio"
    return f"{region} {super_region}".strip()


def load_label_overrides(directory: Path = REFERENCE_DIR) -> dict[str, dict[str, str]]:
    path = directory / ZONE_LABELS_FILE
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _derive_calibration(conn: psycopg.Connection, map_id: int) -> None:
    row = conn.execute(
        f"""SELECT percentile_cont(0.005) WITHIN GROUP (ORDER BY t.x), percentile_cont(0.995) WITHIN GROUP (ORDER BY t.x),
                   percentile_cont(0.005) WITHIN GROUP (ORDER BY t.y), percentile_cont(0.995) WITHIN GROUP (ORDER BY t.y)
            FROM analytics.position_samples t {BY_MAP}""",
        (map_id,),
    ).fetchone()
    assert row is not None
    x_min, x_max, y_min, y_max = row
    span = max(x_max - x_min, y_max - y_min) * 1.1
    x_mult, y_mult = 1 / span, -1 / span
    conn.execute(
        """UPDATE analytics.maps SET x_mult = %s, y_mult = %s, x_add = %s, y_add = %s, calibration = 'derived'
           WHERE id = %s""",
        (x_mult, y_mult, 0.5 - (y_min + y_max) / 2 * x_mult, 0.5 - (x_min + x_max) / 2 * y_mult, map_id),
    )


def _points(conn: psycopg.Connection, query: str, map_id: int) -> NDArray[np.float64]:
    return np.array(conn.execute(query, (map_id,)).fetchall(), dtype=np.float64).reshape(-1, 2)


def _anchors(
    conn: psycopg.Connection,
    map_id: int,
    map_name: str,
    positions: NDArray[np.float64],
    overrides: dict[str, dict[str, str]],
) -> tuple[list[Anchor], str]:
    callouts = conn.execute(
        """SELECT region, super_region, nx, ny FROM analytics.map_callouts
           WHERE map_id = %s ORDER BY super_region, region""",
        (map_id,),
    ).fetchall()
    if not callouts:
        return cluster_anchors(positions), "cluster"
    renames = overrides.get(map_name, {})
    anchors = [
        Anchor(renames.get(f"{sup}/{reg}", zone_label(reg, sup)), reg, sup, float(nx), float(ny))
        for reg, sup, nx, ny in callouts
    ]
    return merge_duplicate_anchors(anchors), "callout"


def _write_geometry(
    conn: psycopg.Connection,
    map_id: int,
    zones: list[Zone],
    zone_ids: list[int],
    sites: dict[str, tuple[float, float, int]],
) -> None:
    conn.execute("DELETE FROM analytics.zones WHERE map_id = %s", (map_id,))
    conn.execute("DELETE FROM analytics.map_sites WHERE map_id = %s", (map_id,))
    with conn.cursor() as cur:
        with cur.copy(
            """COPY analytics.zones (id, map_id, name, region, super_region, source, anchor_nx, anchor_ny,
                                     label_nx, label_ny, area, path_svg) FROM STDIN"""
        ) as copy:
            for zone_id, zone in zip(zone_ids, zones, strict=True):
                a = zone.anchor
                copy.write_row((
                    zone_id, map_id, a.name, a.region, a.super_region, zone.source, a.x, a.y,
                    zone.centroid[0], zone.centroid[1], zone.area, zone.svg_path,
                ))
        with cur.copy("COPY analytics.map_sites (map_id, site, nx, ny, plants) FROM STDIN") as copy:
            for site, (nx, ny, count) in sites.items():
                copy.write_row((map_id, site, nx, ny, count))


def _assign_zones(conn: psycopg.Connection, map_id: int, index: ZoneIndex, zone_ids: list[int]) -> None:
    for select_sql, update_sql in ZONE_TARGETS:
        rows = conn.execute(select_sql, (map_id,)).fetchall()
        if not rows:
            continue
        nearest = index.assign(np.array([(row[2], row[3]) for row in rows], dtype=np.float64))
        conn.execute("CREATE TEMP TABLE zone_assign (k1 bigint, k2 bigint, zone_id integer) ON COMMIT DROP")
        with conn.cursor() as cur, cur.copy("COPY zone_assign (k1, k2, zone_id) FROM STDIN") as copy:
            for row, i in zip(rows, nearest, strict=True):
                copy.write_row((row[0], row[1], zone_ids[i]))
        conn.execute(update_sql)
        conn.execute("DROP TABLE zone_assign")


def build_map(conn: psycopg.Connection, map_id: int, overrides: dict[str, dict[str, str]]) -> MapGeometry:
    row = conn.execute("SELECT name, x_mult FROM analytics.maps WHERE id = %s", (map_id,)).fetchone()
    assert row is not None
    name, x_mult = row
    if x_mult is None:
        _derive_calibration(conn, map_id)
    for statement in NORMALIZE:
        conn.execute(statement, (map_id,))

    positions = _points(conn, f"SELECT t.nx, t.ny FROM analytics.position_samples t {BY_MAP}", map_id)
    victims = _points(conn, f"SELECT t.victim_nx, t.victim_ny FROM analytics.kills t {BY_MAP}", map_id)
    plants = conn.execute(
        f"SELECT r.plant_site, r.plant_nx, r.plant_ny {ROUNDS_BY_MAP} AND r.plant_site IS NOT NULL", (map_id,)
    ).fetchall()
    plant_points = np.array([(p[1], p[2]) for p in plants], dtype=np.float64).reshape(-1, 2)

    silhouette = build_silhouette(np.vstack([positions, victims, plant_points]))
    anchors, source = _anchors(conn, map_id, name, positions, overrides)
    zones = build_zones(anchors, silhouette.shape, source)
    zone_ids = [map_id * 1000 + i for i in range(len(zones))]
    sites = site_centroids([(site, float(nx), float(ny)) for site, nx, ny in plants])

    minx, miny, maxx, maxy = silhouette.shape.bounds
    bounds = {
        "viewBox": [0, 0, SVG_SCALE, SVG_SCALE],
        "content": [round(v * SVG_SCALE, 1) for v in (minx, miny, maxx, maxy)],
        "sampleSize": silhouette.sample_size,
    }
    conn.execute(
        "UPDATE analytics.maps SET silhouette_svg = %s, silhouette_quality = %s, bounds = %s WHERE id = %s",
        (silhouette.svg_path, silhouette.quality, json.dumps(bounds), map_id),
    )
    _write_geometry(conn, map_id, zones, zone_ids, sites)
    _assign_zones(conn, map_id, ZoneIndex([zone.anchor for zone in zones]), zone_ids)
    return MapGeometry(map_id, name, silhouette.sample_size, silhouette.quality, len(zones), source, tuple(sites))


def build_geometry(conn: psycopg.Connection) -> list[MapGeometry]:
    overrides = load_label_overrides()
    map_ids = [row[0] for row in conn.execute("SELECT DISTINCT map_id FROM analytics.matches ORDER BY 1")]
    results = []
    for map_id in map_ids:
        with conn.transaction():
            results.append(build_map(conn, map_id, overrides))
    return results
