from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from shapely import MultiPoint, MultiPolygon, Polygon, make_valid
from shapely.geometry.base import BaseGeometry
from skimage import measure, morphology

GRID = 512
SVG_SCALE = 1000
LOW_QUALITY_BELOW = 10_000
HULL_MARGIN = 0.02


@dataclass(frozen=True, slots=True)
class Silhouette:
    shape: MultiPolygon
    svg_path: str
    sample_size: int
    quality: str


def _radius_for(sample_size: int) -> int:
    if sample_size >= 50_000:
        return 3
    if sample_size >= 20_000:
        return 4
    if sample_size >= LOW_QUALITY_BELOW:
        return 6
    return 9


def occupancy_mask(points: NDArray[np.float64], radius: int) -> NDArray[np.bool_]:
    inside = points[(points >= 0).all(axis=1) & (points <= 1).all(axis=1)]
    cells = np.minimum((inside * GRID).astype(int), GRID - 1)
    mask = np.zeros((GRID, GRID), dtype=bool)
    mask[cells[:, 1], cells[:, 0]] = True
    mask = morphology.dilation(mask, morphology.disk(radius))
    mask = morphology.closing(mask, morphology.disk(radius))
    mask = morphology.remove_small_objects(mask, max_size=40 * radius * radius)
    return morphology.remove_small_holes(mask, max_size=12 * radius * radius)


def mask_to_shape(mask: NDArray[np.bool_], tolerance: float) -> MultiPolygon:
    padded = np.pad(mask, 1).astype(np.uint8)
    rings = [
        Polygon([((col - 1) / GRID, (row - 1) / GRID) for row, col in contour])
        for contour in measure.find_contours(padded, 0.5)
        if len(contour) >= 4
    ]
    rings.sort(key=lambda ring: ring.area, reverse=True)
    shape: BaseGeometry = Polygon()
    for ring in rings:
        ring = make_valid(ring)
        shape = shape.difference(ring) if shape.contains(ring) else shape.union(ring)
    shape = shape.simplify(tolerance, preserve_topology=True)
    polygons = [g for g in getattr(shape, "geoms", [shape]) if isinstance(g, Polygon) and not g.is_empty]
    return MultiPolygon(polygons)


def to_svg_path(shape: BaseGeometry) -> str:
    def ring(coords: Sequence[tuple[float, float]]) -> str:
        points = [f"{x * SVG_SCALE:.1f} {y * SVG_SCALE:.1f}" for x, y in coords[:-1]]
        return "M" + " L".join(points) + " Z"

    parts: list[str] = []
    for polygon in getattr(shape, "geoms", [shape]):
        if not isinstance(polygon, Polygon) or polygon.is_empty:
            continue
        parts.append(ring(list(polygon.exterior.coords)))
        parts.extend(ring(list(interior.coords)) for interior in polygon.interiors)
    return " ".join(parts)


def build_silhouette(points: NDArray[np.float64]) -> Silhouette:
    radius = _radius_for(len(points))
    shape = mask_to_shape(occupancy_mask(points, radius), tolerance=0.6 / GRID)
    if shape.is_empty:
        shape = MultiPolygon([MultiPoint(points.clip(0, 1)).convex_hull.buffer(HULL_MARGIN)])
    return Silhouette(
        shape=shape,
        svg_path=to_svg_path(shape),
        sample_size=len(points),
        quality="low" if len(points) < LOW_QUALITY_BELOW else "ok",
    )
