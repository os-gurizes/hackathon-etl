import numpy as np
from shapely import Point

from vstats.geometry.build import zone_label
from vstats.geometry.silhouette import build_silhouette, to_svg_path
from vstats.geometry.zones import (
    Anchor,
    ZoneIndex,
    build_zones,
    cluster_anchors,
    merge_duplicate_anchors,
    site_centroids,
)

RNG = np.random.default_rng(42)


def ring_points(n: int = 60_000) -> np.ndarray:
    points = RNG.uniform(0.2, 0.8, size=(n * 2, 2))
    inner = (np.abs(points - 0.5) < 0.12).all(axis=1)
    return points[~inner][:n]


def test_silhouette_covers_points_and_keeps_large_holes() -> None:
    silhouette = build_silhouette(ring_points())
    assert silhouette.quality == "ok"
    assert silhouette.shape.contains(Point(0.25, 0.25))
    assert not silhouette.shape.contains(Point(0.5, 0.5))
    assert not silhouette.shape.contains(Point(0.05, 0.05))


def test_sparse_maps_are_flagged_low_quality() -> None:
    assert build_silhouette(ring_points(3_000)).quality == "low"


def test_points_outside_minimap_are_ignored() -> None:
    points = np.vstack([ring_points(), [[0.5, 4.4], [-1.0, 0.3]]])
    minx, miny, maxx, maxy = build_silhouette(points).shape.bounds
    assert minx >= 0.15 and maxy <= 0.85


def test_svg_path_uses_thousand_unit_viewbox() -> None:
    path = to_svg_path(build_silhouette(ring_points()).shape)
    assert path.startswith("M") and path.endswith("Z")
    coords = [float(v) for v in path.replace("M", " ").replace("L", " ").replace("Z", " ").split()]
    assert 150 < min(coords) and max(coords) < 850


def test_zones_partition_silhouette_and_assign_nearest_anchor() -> None:
    silhouette = build_silhouette(ring_points()).shape
    anchors = [
        Anchor("Fundos A", "Fundos", "A", 0.25, 0.25),
        Anchor("Fundos B", "Fundos", "B", 0.75, 0.75),
        Anchor("Link do Meio", "Link", "Meio", 0.75, 0.25),
    ]
    zones = build_zones(anchors, silhouette, "callout")
    assert len(zones) == 3
    assert abs(sum(z.area for z in zones) - silhouette.area) < 1e-6
    assigned = ZoneIndex(anchors).assign(np.array([[0.3, 0.3], [0.7, 0.8], [0.8, 0.2]]))
    assert assigned.tolist() == [0, 1, 2]


def test_cluster_fallback_is_deterministic() -> None:
    points = ring_points(5_000)
    first, second = cluster_anchors(points), cluster_anchors(points)
    assert first == second and len(first) == 24 and first[0].name == "Zona 1"


def test_zone_labels() -> None:
    assert zone_label("Árvore", "A") == "Árvore A"
    assert zone_label("Ladrilhos", "Meio") == "Ladrilhos do Meio"
    assert zone_label("Base", "no Lado Defensor") == "Base no Lado Defensor"


def test_site_centroid_is_robust_to_outliers() -> None:
    plants = [("A", 0.2, 0.2)] * 9 + [("A", 0.9, 0.9), ("B", 0.7, 0.7)]
    sites = site_centroids(plants)
    assert sites["A"] == (0.2, 0.2, 10) and sites["B"][2] == 1


def test_callouts_at_the_same_point_become_one_zone() -> None:
    anchors = [
        Anchor("Clube B", "Clube", "B", 0.4, 0.4),
        Anchor("Lojas do Meio", "Lojas", "Meio", 0.4, 0.4),
        Anchor("Ponto A", "Ponto", "A", 0.7, 0.7),
    ]
    merged = merge_duplicate_anchors(anchors)
    assert [a.name for a in merged] == ["Clube B / Lojas do Meio", "Ponto A"]
