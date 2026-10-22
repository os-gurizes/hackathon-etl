from collections.abc import Iterator
from html import escape

import psycopg

from vstats.geometry.silhouette import SVG_SCALE


def render_map_svgs(conn: psycopg.Connection) -> Iterator[tuple[str, str]]:
    maps = conn.execute(
        "SELECT id, slug, name, silhouette_svg FROM analytics.maps WHERE silhouette_svg IS NOT NULL ORDER BY slug"
    ).fetchall()
    for map_id, slug, name, silhouette in maps:
        zones = conn.execute(
            "SELECT name, path_svg, label_nx, label_ny FROM analytics.zones WHERE map_id = %s", (map_id,)
        ).fetchall()
        sites = conn.execute("SELECT site, nx, ny FROM analytics.map_sites WHERE map_id = %s", (map_id,)).fetchall()
        parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SVG_SCALE} {SVG_SCALE}">',
            f"<title>{escape(name)}</title>",
            '<rect width="100%" height="100%" fill="#0F1923"/>',
            f'<path d="{silhouette}" fill="#1F2D3A" fill-rule="evenodd"/>',
        ]
        parts += [f'<path d="{path}" fill="none" stroke="#2C3B49" stroke-width="1.5"/>' for _, path, _, _ in zones]
        parts += [
            f'<text x="{x * SVG_SCALE:.0f}" y="{y * SVG_SCALE:.0f}" font-size="11" fill="#9AA3AD" '
            f'text-anchor="middle" font-family="sans-serif">{escape(label)}</text>'
            for label, _, x, y in zones
        ]
        parts += [
            f'<text x="{x * SVG_SCALE:.0f}" y="{y * SVG_SCALE:.0f}" font-size="34" font-weight="700" fill="#FF4655" '
            f'text-anchor="middle" dominant-baseline="middle" font-family="sans-serif">{escape(site)}</text>'
            for site, x, y in sites
        ]
        parts.append("</svg>")
        yield slug, "\n".join(parts)
