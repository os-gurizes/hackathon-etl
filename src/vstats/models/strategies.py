import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from statistics import median

import numpy as np
import psycopg
from numpy.typing import NDArray
from sklearn.cluster import HDBSCAN
from sklearn.decomposition import PCA

SETUP_WINDOW_MS = 40_000
MIN_ROUNDS_TO_CLUSTER = 80
FAST_EXECUTE_S = 40
SLOW_EXECUTE_S = 70
DOMINANT_SITE_SHARE = 0.6
REGION_WEIGHT = 2.0
BASE_REGIONS = {"no Lado Atacante", "no Lado Defensor"}
NOISE_INDEX = 49

POSITIONS_SQL = """
    SELECT ps.round_id, ps.player_id, ps.t_round_ms, ps.zone_id
    FROM analytics.position_samples ps WHERE ps.zone_id IS NOT NULL
    UNION ALL
    SELECT k.round_id, k.victim_id, k.t_round_ms, k.victim_zone_id
    FROM analytics.kills k WHERE k.victim_zone_id IS NOT NULL
"""

ROUNDS_SQL = """
    SELECT r.id, m.map_id, rp.team_id, rp.side, (r.winner_team_id = rp.team_id),
           r.plant_site, r.plant_time_ms, array_agg(rp.player_id ORDER BY rp.player_id),
           (SELECT k.t_round_ms FROM analytics.kills k WHERE k.round_id = r.id ORDER BY k.seq OFFSET 1 LIMIT 1)
    FROM analytics.rounds r
    JOIN analytics.matches m ON m.id = r.match_id
    JOIN analytics.round_players rp ON rp.round_id = r.id
    GROUP BY r.id, m.map_id, rp.team_id, rp.side
"""


@dataclass(frozen=True, slots=True)
class TeamRound:
    round_id: int
    map_id: int
    team_id: int
    side: str
    won: bool
    plant_site: str | None
    plant_time_ms: int | None
    zones: tuple[int, ...]


def region_of(super_region: str) -> str:
    return "Base" if super_region in BASE_REGIONS or not super_region else super_region


def setup_zones(samples: list[tuple[int, int]], cutoff_ms: int) -> int | None:
    inside = [s for s in samples if s[0] <= cutoff_ms]
    return max(inside)[1] if inside else None


def wilson(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = wins / n
    denominator = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return max(0.0, center - margin), min(1.0, center + margin)


def load_team_rounds(conn: psycopg.Connection) -> list[TeamRound]:
    samples: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
    for round_id, player_id, t, zone_id in conn.execute(POSITIONS_SQL):
        samples[(round_id, player_id)].append((t, zone_id))
    rounds = []
    for round_id, map_id, team_id, side, won, plant_site, plant_time, players, second_kill in conn.execute(ROUNDS_SQL):
        cutoff = min(SETUP_WINDOW_MS, second_kill if second_kill is not None else SETUP_WINDOW_MS)
        zones = tuple(z for p in players if (z := setup_zones(samples[(round_id, p)], cutoff)) is not None)
        rounds.append(TeamRound(round_id, map_id, team_id, side, won, plant_site, plant_time, zones))
    return rounds


def featurize(rounds: list[TeamRound], zone_ids: list[int], region_of_zone: dict[int, str],
              regions: list[str]) -> NDArray[np.float64]:
    zone_index = {z: i for i, z in enumerate(zone_ids)}
    rows = []
    for r in rounds:
        zone_vec = np.zeros(len(zone_ids))
        region_vec = np.zeros(len(regions))
        for z in r.zones:
            zone_vec[zone_index[z]] += 1
            region_vec[regions.index(region_of_zone[z])] += 1
        total = max(len(r.zones), 1)
        rows.append(np.concatenate([zone_vec / total, REGION_WEIGHT * region_vec / total]))
    return np.array(rows)


def apportion(shares: dict[str, float], total: int) -> dict[str, int]:
    floors = {k: math.floor(v) for k, v in shares.items()}
    remaining = total - sum(floors.values())
    for key in sorted(shares, key=lambda k: shares[k] - floors[k], reverse=True)[:max(remaining, 0)]:
        floors[key] += 1
    return {k: v for k, v in sorted(floors.items(), key=lambda item: -item[1]) if v > 0}


def _region_phrase(region: str, count: int) -> str:
    if region == "Meio":
        return f"{count} no Meio"
    if region == "Base":
        return f"{count} na base"
    return f"{count} no {region}"


@dataclass(frozen=True, slots=True)
class Description:
    title: str
    detail: str
    region_counts: dict[str, int]
    top_zones: list[dict[str, object]]
    plant_sites: dict[str, float]
    plant_time_s: float | None


def describe(members: list[TeamRound], side: str, region_of_zone: dict[int, str],
             zone_names: dict[int, str]) -> Description:
    region_totals: Counter[str] = Counter()
    zone_totals: Counter[int] = Counter()
    for r in members:
        for z in r.zones:
            region_totals[region_of_zone[z]] += 1
            zone_totals[z] += 1
    team_size = round(sum(len(r.zones) for r in members) / len(members))
    region_counts = apportion({k: v / len(members) for k, v in region_totals.items()}, team_size)
    top_zones = [
        {"zoneId": z, "name": zone_names[z], "share": round(c / len(members), 2)} for z, c in zone_totals.most_common(5)
    ]
    focus = zone_names[zone_totals.most_common(1)[0][0]]
    planted = [r for r in members if r.plant_site]
    plant_sites = {s: round(c / len(members), 2) for s, c in Counter(r.plant_site for r in planted).most_common()}
    plant_time = round(median(r.plant_time_ms for r in planted) / 1000, 1) if planted else None
    spread = ", ".join(_region_phrase(region, n) for region, n in region_counts.items())

    if side == "defense":
        sites = {r: n for r, n in region_counts.items() if r in ("A", "B", "C")}
        top_region, top_count = max(sites.items(), key=lambda item: item[1], default=("", 0))
        title = f"Stack de {top_count} no {top_region}" if top_count >= 3 else f"Defesa {spread}"
        return Description(f"{title}, foco em {focus}", f"Posicionamento inicial: {spread}.",
                           region_counts, top_zones, plant_sites, plant_time)

    plant_share = sum(plant_sites.values())
    site = next(iter(plant_sites), None)
    site_plants = [r.plant_time_ms for r in planted if r.plant_site == site]
    if plant_share < 0.4 or site is None:
        title = f"Ataque pelo {focus} sem plant frequente"
    elif len(site_plants) < DOMINANT_SITE_SHARE * len(planted):
        title = f"Ataque dividido entre {' e '.join(plant_sites)} pelo {focus}"
    else:
        site_time = median(site_plants) / 1000
        pace = (
            "Execução rápida" if site_time < FAST_EXECUTE_S
            else "Default lento" if site_time > SLOW_EXECUTE_S
            else "Ataque em ritmo médio"
        )
        title = f"{pace} no {site} pelo {focus}"
    detail = f"Posicionamento inicial: {spread}."
    if plant_time is not None:
        detail += f" Plant em {round(plant_share * 100)}% dos rounds, mediana de {plant_time:.0f} s."
    return Description(title, detail, region_counts, top_zones, plant_sites, plant_time)


@dataclass(frozen=True, slots=True)
class StrategySummary:
    map_id: int
    side: str
    rounds: int
    clusters: int
    noise_share: float


def build_strategies(conn: psycopg.Connection) -> list[StrategySummary]:
    zone_rows = conn.execute("SELECT id, map_id, name, super_region FROM analytics.zones ORDER BY id").fetchall()
    region_of_zone = {z: region_of(sup) for z, _, _, sup in zone_rows}
    zone_names = {z: name for z, _, name, _ in zone_rows}
    zones_by_map: dict[int, list[int]] = defaultdict(list)
    for z, map_id, _, _ in zone_rows:
        zones_by_map[map_id].append(z)

    groups: dict[tuple[int, str], list[TeamRound]] = defaultdict(list)
    for r in load_team_rounds(conn):
        if r.zones:
            groups[(r.map_id, r.side)].append(r)

    strategy_rows: list[tuple[object, ...]] = []
    assignment_rows: list[tuple[object, ...]] = []
    summaries: list[StrategySummary] = []
    for (map_id, side), rounds in sorted(groups.items()):
        side_code = 0 if side == "attack" else 1
        labels = np.full(len(rounds), -1)
        confidence = np.zeros(len(rounds))
        if len(rounds) >= MIN_ROUNDS_TO_CLUSTER:
            regions = sorted({region_of_zone[z] for z in zones_by_map[map_id]})
            x = featurize(rounds, zones_by_map[map_id], region_of_zone, regions)
            reduced = PCA(n_components=min(10, x.shape[1]), random_state=42).fit_transform(x)
            model = HDBSCAN(min_cluster_size=max(15, len(rounds) // 40), min_samples=5, copy=True).fit(reduced)
            labels, confidence = model.labels_, model.probabilities_

        seen_titles: Counter[str] = Counter()
        for cluster in sorted(set(labels.tolist())):
            members = [r for r, label in zip(rounds, labels, strict=True) if label == cluster]
            is_noise = cluster == -1
            index = NOISE_INDEX if is_noise else cluster
            strategy_id = map_id * 100 + side_code * 50 + index
            info = describe(members, side, region_of_zone, zone_names)
            title = "Sem padrão definido" if is_noise else info.title
            seen_titles[title] += 1
            if seen_titles[title] > 1:
                title = f"{title} (variação {seen_titles[title]})"
            wins = sum(r.won for r in members)
            low, high = wilson(wins, len(members))
            strategy_rows.append((
                strategy_id, map_id, side, is_noise, title, info.detail, len(members), wins, wins / len(members),
                low, high, json.dumps(info.region_counts, ensure_ascii=False),
                json.dumps(info.top_zones, ensure_ascii=False), json.dumps(info.plant_sites), info.plant_time_s,
            ))
            for r, label, conf in zip(rounds, labels, confidence, strict=True):
                if label == cluster:
                    assignment_rows.append((r.round_id, r.team_id, side, strategy_id, float(conf), r.won))
        clusters = len(set(labels.tolist()) - {-1})
        summaries.append(StrategySummary(map_id, side, len(rounds), clusters, float(np.mean(labels == -1))))

    with conn.transaction():
        conn.execute("TRUNCATE analytics.round_strategy, analytics.strategies")
        with conn.cursor() as cur:
            with cur.copy(
                """COPY analytics.strategies (id, map_id, side, is_noise, title, description, rounds, wins, win_rate,
                       ci_low, ci_high, region_counts, top_zones, plant_sites, plant_time_s) FROM STDIN"""
            ) as copy:
                for row in strategy_rows:
                    copy.write_row(row)
            with cur.copy(
                "COPY analytics.round_strategy (round_id, team_id, side, strategy_id, confidence, won) FROM STDIN"
            ) as copy:
                for row in assignment_rows:
                    copy.write_row(row)
    return summaries
