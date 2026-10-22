from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.spatial import cKDTree
from shapely import MultiPoint, MultiPolygon, Point, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import voronoi_diagram
from sklearn.cluster import KMeans

from vstats.geometry.silhouette import to_svg_path

FALLBACK_ZONES = 24
SEED = 42


@dataclass(frozen=True, slots=True)
class Anchor:
    name: str
    region: str
    super_region: str
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class Zone:
    anchor: Anchor
    source: str
    shape: BaseGeometry
    svg_path: str
    centroid: tuple[float, float]
    area: float


def cluster_anchors(points: NDArray[np.float64]) -> list[Anchor]:
    k = min(FALLBACK_ZONES, len(points))
    centers = KMeans(n_clusters=k, n_init=10, random_state=SEED).fit(points).cluster_centers_.round(6)
    order = np.lexsort((centers[:, 0], centers[:, 1]))
    return [
        Anchor(f"Zona {i + 1}", f"Zona {i + 1}", "", float(centers[j, 0]), float(centers[j, 1]))
        for i, j in enumerate(order)
    ]


def merge_duplicate_anchors(anchors: list[Anchor]) -> list[Anchor]:
    merged: dict[tuple[float, float], Anchor] = {}
    for anchor in anchors:
        key = (round(anchor.x, 6), round(anchor.y, 6))
        found = merged.get(key)
        if found is None:
            merged[key] = anchor
        else:
            merged[key] = Anchor(f"{found.name} / {anchor.name}", f"{found.region} / {anchor.region}",
                                 found.super_region, found.x, found.y)
    return list(merged.values())


def build_zones(anchors: list[Anchor], silhouette: MultiPolygon, source: str) -> list[Zone]:
    seeds = MultiPoint([(a.x, a.y) for a in anchors])
    cells = voronoi_diagram(seeds, envelope=box(-0.5, -0.5, 1.5, 1.5))
    zones: list[Zone] = []
    for anchor in anchors:
        seed = Point(anchor.x, anchor.y)
        cell = next(c for c in cells.geoms if c.contains(seed) or c.touches(seed))
        shape = cell.intersection(silhouette) if not silhouette.is_empty else cell
        if shape.is_empty:
            continue
        centroid = shape.representative_point()
        zones.append(
            Zone(anchor, source, shape, to_svg_path(shape), (centroid.x, centroid.y), shape.area)
        )
    return zones


class ZoneIndex:
    def __init__(self, anchors: list[Anchor]) -> None:
        self._tree = cKDTree(np.array([(a.x, a.y) for a in anchors]))

    def assign(self, points: NDArray[np.float64]) -> NDArray[np.int64]:
        _, index = self._tree.query(points)
        return np.asarray(index, dtype=np.int64)


def site_centroids(plants: list[tuple[str, float, float]]) -> dict[str, tuple[float, float, int]]:
    by_site: dict[str, list[tuple[float, float]]] = {}
    for site, x, y in plants:
        by_site.setdefault(site, []).append((x, y))
    return {
        site: (float(np.median([p[0] for p in pts])), float(np.median([p[1] for p in pts])), len(pts))
        for site, pts in sorted(by_site.items())
    }
