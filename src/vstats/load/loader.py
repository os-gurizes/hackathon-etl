import hashlib
from collections.abc import Iterable, Sequence
from typing import Any

import psycopg

from vstats.catalog import Stage
from vstats.quality import Issue
from vstats.reference.resolver import Reference
from vstats.transform import MatchRecord


def puuid_hash(puuid: str) -> str:
    return hashlib.sha256(puuid.encode()).hexdigest()


def round_id(match_id: int, number: int) -> int:
    return match_id * 100 + number


def kill_id(round_id_: int, seq: int) -> int:
    return round_id_ * 100 + seq


def _copy(cur: psycopg.Cursor, table: str, columns: Sequence[str], rows: Iterable[Sequence[Any]]) -> None:
    with cur.copy(f"COPY analytics.{table} ({', '.join(columns)}) FROM STDIN") as copy:
        for row in rows:
            copy.write_row(row)


class Loader:
    def __init__(self, conn: psycopg.Connection, reference: Reference) -> None:
        self.conn = conn
        self.reference = reference
        self.agents: dict[str, int] = {}
        self.weapons: dict[str, int] = {}
        self.maps: dict[str, int] = {}
        self.teams: dict[str, int] = {}
        self.players: dict[str, int] = {}
        self.stages: dict[tuple[str, str], int] = {}

    def start_run(self, source: str, pipeline_version: str) -> int:
        row = self.conn.execute(
            "INSERT INTO analytics.ingest_runs (source, pipeline_version) VALUES (%s, %s) RETURNING id",
            (source, pipeline_version),
        ).fetchone()
        assert row is not None
        return int(row[0])

    def finish_run(self, run_id: int, seen: int, loaded: int, skipped: int, issues: Sequence[Issue]) -> None:
        self.conn.execute(
            """UPDATE analytics.ingest_runs
               SET finished_at = now(), files_seen = %s, files_loaded = %s, files_skipped = %s
               WHERE id = %s""",
            (seen, loaded, skipped, run_id),
        )
        with self.conn.cursor() as cur:
            _copy(
                cur,
                "data_quality_report",
                ("run_id", "severity", "code", "source_file", "detail"),
                ((run_id, i.severity, i.code, i.source_file, i.detail) for i in issues),
            )

    def load_dimensions(self, matches: Sequence[MatchRecord]) -> None:
        agent_uuids = {p.agent_uuid for m in matches for p in m.players}
        weapon_uuids = {uuid for uuid in self.reference.weapons} | {
            uuid
            for m in matches
            for r in m.rounds
            for uuid in [
                *(k.weapon_uuid for k in r.kills),
                *(p.weapon_uuid for p in r.players),
                *(p.armor_uuid for p in r.players),
            ]
            if uuid is not None
        }
        self._upsert_agents(agent_uuids)
        self._upsert_weapons(weapon_uuids)
        self._upsert_maps({m.map_internal_name: m.meta.map_slug for m in matches})
        self._upsert_stages({m.meta.stage for m in matches})
        self._upsert_teams({slug for m in matches for slug in (m.red_slug, m.blue_slug)})
        self._upsert_players(matches)

    def _upsert_agents(self, uuids: set[str]) -> None:
        for uuid in sorted(uuids):
            agent = self.reference.agent(uuid)
            row = self.conn.execute(
                """INSERT INTO analytics.agents (uuid, name, role, ability_grenade, ability_1, ability_2, ultimate)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (uuid) DO UPDATE SET name = EXCLUDED.name, role = EXCLUDED.role,
                       ability_grenade = EXCLUDED.ability_grenade, ability_1 = EXCLUDED.ability_1,
                       ability_2 = EXCLUDED.ability_2, ultimate = EXCLUDED.ultimate
                   RETURNING id""",
                (
                    agent.uuid,
                    agent.name,
                    agent.role,
                    agent.abilities.get("Grenade"),
                    agent.abilities.get("Ability1"),
                    agent.abilities.get("Ability2"),
                    agent.abilities.get("Ultimate"),
                ),
            ).fetchone()
            assert row is not None
            self.agents[uuid] = int(row[0])

    def _upsert_weapons(self, uuids: set[str]) -> None:
        for uuid in sorted(uuids):
            weapon = self.reference.weapon(uuid)
            row = self.conn.execute(
                """INSERT INTO analytics.weapons (uuid, name, category, cost, is_armor)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (uuid) DO UPDATE SET name = EXCLUDED.name, category = EXCLUDED.category,
                       cost = EXCLUDED.cost, is_armor = EXCLUDED.is_armor
                   RETURNING id""",
                (weapon.uuid, weapon.name, weapon.category, weapon.cost, weapon.is_armor),
            ).fetchone()
            assert row is not None
            self.weapons[uuid] = int(row[0])

    def _upsert_maps(self, slugs: dict[str, str]) -> None:
        for internal_name, slug in sorted(slugs.items()):
            ref = self.reference.map(internal_name)
            row = self.conn.execute(
                """INSERT INTO analytics.maps (internal_name, slug, name, x_mult, y_mult, x_add, y_add)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (internal_name) DO UPDATE SET slug = EXCLUDED.slug, name = EXCLUDED.name,
                       x_mult = EXCLUDED.x_mult, y_mult = EXCLUDED.y_mult,
                       x_add = EXCLUDED.x_add, y_add = EXCLUDED.y_add
                   RETURNING id""",
                (
                    internal_name,
                    slug,
                    ref.name if ref else slug.title(),
                    ref.x_mult if ref else None,
                    ref.y_mult if ref else None,
                    ref.x_add if ref else None,
                    ref.y_add if ref else None,
                ),
            ).fetchone()
            assert row is not None
            map_id = int(row[0])
            self.maps[internal_name] = map_id
            if ref is None:
                continue
            self.conn.execute("DELETE FROM analytics.map_callouts WHERE map_id = %s", (map_id,))
            with self.conn.cursor() as cur:
                _copy(
                    cur,
                    "map_callouts",
                    ("map_id", "region", "super_region", "x", "y", "nx", "ny"),
                    (
                        (map_id, c.region, c.super_region, c.x, c.y, *ref.normalize(c.x, c.y))
                        for c in {(c.super_region, c.region): c for c in ref.callouts}.values()
                    ),
                )

    def _upsert_stages(self, stages: set[Stage]) -> None:
        for stage in sorted(stages, key=lambda s: (s.tournament.slug, s.order)):
            row = self.conn.execute(
                """INSERT INTO analytics.tournaments (slug, name) VALUES (%s, %s)
                   ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name RETURNING id""",
                (stage.tournament.slug, stage.tournament.name),
            ).fetchone()
            assert row is not None
            stage_row = self.conn.execute(
                """INSERT INTO analytics.stages (tournament_id, slug, name, sort_order) VALUES (%s, %s, %s, %s)
                   ON CONFLICT (tournament_id, slug) DO UPDATE SET name = EXCLUDED.name,
                       sort_order = EXCLUDED.sort_order
                   RETURNING id""",
                (row[0], stage.slug, stage.name, stage.order),
            ).fetchone()
            assert stage_row is not None
            self.stages[(stage.tournament.slug, stage.slug)] = int(stage_row[0])

    def _upsert_teams(self, slugs: set[str]) -> None:
        for slug in sorted(slugs):
            row = self.conn.execute(
                """INSERT INTO analytics.teams (slug, display_name) VALUES (%s, %s)
                   ON CONFLICT (slug) DO UPDATE SET display_name = EXCLUDED.display_name RETURNING id""",
                (slug, self.reference.team_name(slug)),
            ).fetchone()
            assert row is not None
            self.teams[slug] = int(row[0])

    def _upsert_players(self, matches: Sequence[MatchRecord]) -> None:
        latest: dict[str, tuple[Any, str, str]] = {}
        for match in matches:
            for player in match.players:
                seen = latest.get(player.puuid)
                if seen is None or seen[0] < match.started_at:
                    latest[player.puuid] = (match.started_at, player.game_name, player.tag_line)
        for puuid, (seen_at, game_name, tag_line) in sorted(latest.items()):
            row = self.conn.execute(
                """INSERT INTO analytics.players (puuid_hash, game_name, tag_line, last_seen_at)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (puuid_hash) DO UPDATE SET
                       game_name = CASE WHEN EXCLUDED.last_seen_at >= players.last_seen_at
                                        THEN EXCLUDED.game_name ELSE players.game_name END,
                       tag_line = CASE WHEN EXCLUDED.last_seen_at >= players.last_seen_at
                                       THEN EXCLUDED.tag_line ELSE players.tag_line END,
                       last_seen_at = GREATEST(players.last_seen_at, EXCLUDED.last_seen_at)
                   RETURNING id""",
                (puuid_hash(puuid), game_name, tag_line, seen_at),
            ).fetchone()
            assert row is not None
            self.players[puuid] = int(row[0])

    def _series_id(self, match: MatchRecord) -> int:
        meta = match.meta
        stage_id = self.stages[(meta.stage.tournament.slug, meta.stage.slug)]
        row = self.conn.execute(
            """INSERT INTO analytics.series (stage_id, number, team_a_id, team_b_id)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (stage_id, number) DO UPDATE SET number = EXCLUDED.number
               RETURNING id""",
            (stage_id, meta.series_number, self.teams[meta.team_a], self.teams[meta.team_b]),
        ).fetchone()
        assert row is not None
        return int(row[0])

    def _weapon_id(self, uuid: str | None) -> int | None:
        return self.weapons[uuid] if uuid is not None else None

    def load_match(self, match: MatchRecord, source_file: str) -> int:
        teams, players = self.teams, self.players
        row = self.conn.execute(
            """INSERT INTO analytics.matches (match_uuid, series_id, game_letter, map_id, game_version,
                   played_on, started_at, duration_ms, red_team_id, blue_team_id, winner_team_id,
                   red_score, blue_score, rounds_played, source_file)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (match_uuid) DO UPDATE SET series_id = EXCLUDED.series_id,
                   game_letter = EXCLUDED.game_letter, map_id = EXCLUDED.map_id,
                   game_version = EXCLUDED.game_version, played_on = EXCLUDED.played_on,
                   started_at = EXCLUDED.started_at, duration_ms = EXCLUDED.duration_ms,
                   red_team_id = EXCLUDED.red_team_id, blue_team_id = EXCLUDED.blue_team_id,
                   winner_team_id = EXCLUDED.winner_team_id, red_score = EXCLUDED.red_score,
                   blue_score = EXCLUDED.blue_score, rounds_played = EXCLUDED.rounds_played,
                   source_file = EXCLUDED.source_file
               RETURNING id""",
            (
                match.match_uuid,
                self._series_id(match),
                match.meta.game_letter,
                self.maps[match.map_internal_name],
                match.game_version,
                match.meta.played_on,
                match.started_at,
                match.duration_ms,
                teams[match.red_slug],
                teams[match.blue_slug],
                teams[match.winner_slug],
                match.red_score,
                match.blue_score,
                len(match.rounds),
                source_file,
            ),
        ).fetchone()
        assert row is not None
        match_id = int(row[0])
        self.conn.execute("DELETE FROM analytics.rounds WHERE match_id = %s", (match_id,))
        self.conn.execute("DELETE FROM analytics.match_players WHERE match_id = %s", (match_id,))

        weapon = self._weapon_id
        with self.conn.cursor() as cur:
            _copy(
                cur,
                "match_players",
                ("match_id", "player_id", "team_id", "agent_id", "first_side", "score", "kills",
                 "deaths", "assists", "rounds_played", "casts_grenade", "casts_1", "casts_2", "casts_ult"),
                (
                    (match_id, players[p.puuid], teams[p.team_slug], self.agents[p.agent_uuid],
                     p.first_side, p.score, p.kills, p.deaths, p.assists, p.rounds_played,
                     p.casts_grenade, p.casts_1, p.casts_2, p.casts_ult)
                    for p in match.players
                ),
            )
            _copy(
                cur,
                "rounds",
                ("id", "match_id", "number", "winner_team_id", "winner_side", "attack_team_id",
                 "defense_team_id", "result_code", "ceremony", "plant_site", "plant_time_ms",
                 "planter_id", "plant_x", "plant_y", "defuser_id", "defuse_time_ms"),
                (
                    (round_id(match_id, r.number), match_id, r.number, teams[r.winner_slug],
                     r.winner_side, teams[r.attack_slug], teams[r.defense_slug], r.result_code,
                     r.ceremony, r.plant_site, r.plant_time_ms,
                     players.get(r.planter) if r.planter else None,
                     r.plant_xy[0] if r.plant_xy else None, r.plant_xy[1] if r.plant_xy else None,
                     players.get(r.defuser) if r.defuser else None, r.defuse_time_ms)
                    for r in match.rounds
                ),
            )
            _copy(
                cur,
                "round_players",
                ("round_id", "player_id", "team_id", "side", "score", "loadout_value", "spent",
                 "remaining", "weapon_id", "armor_id", "damage_dealt", "headshots", "bodyshots",
                 "legshots", "kills", "died"),
                (
                    (round_id(match_id, r.number), players[p.puuid], teams[p.team_slug], p.side,
                     p.score, p.loadout_value, p.spent, p.remaining, weapon(p.weapon_uuid),
                     weapon(p.armor_uuid), p.damage_dealt, p.headshots, p.bodyshots, p.legshots,
                     p.kills, p.died)
                    for r in match.rounds
                    for p in r.players
                ),
            )
            _copy(
                cur,
                "kills",
                ("id", "round_id", "seq", "t_round_ms", "t_game_ms", "killer_id", "victim_id",
                 "kind", "damage_type", "weapon_id", "ability_slot", "is_secondary_fire",
                 "killer_x", "killer_y", "victim_x", "victim_y", "distance_m", "is_first_kill",
                 "is_trade", "traded_after_ms"),
                (
                    (kill_id(round_id(match_id, r.number), k.seq), round_id(match_id, r.number),
                     k.seq, k.t_round_ms, k.t_game_ms,
                     players[k.killer] if k.killer else None, players[k.victim], k.kind,
                     k.damage_type, weapon(k.weapon_uuid), k.ability_slot, k.is_secondary_fire,
                     k.killer_xy[0] if k.killer_xy else None, k.killer_xy[1] if k.killer_xy else None,
                     k.victim_xy[0], k.victim_xy[1], k.distance_m, k.is_first_kill, k.is_trade,
                     k.traded_after_ms)
                    for r in match.rounds
                    for k in r.kills
                ),
            )
            _copy(
                cur,
                "kill_assists",
                ("kill_id", "player_id"),
                (
                    (kill_id(round_id(match_id, r.number), k.seq), players[a])
                    for r in match.rounds
                    for k in r.kills
                    for a in dict.fromkeys(k.assistants)
                    if a in players
                ),
            )
            _copy(
                cur,
                "damage_events",
                ("round_id", "dealer_id", "receiver_id", "damage", "headshots", "bodyshots", "legshots"),
                (
                    (round_id(match_id, r.number), players[d.dealer], players[d.receiver],
                     d.damage, d.headshots, d.bodyshots, d.legshots)
                    for r in match.rounds
                    for d in r.damage
                    if d.receiver in players
                ),
            )
            _copy(
                cur,
                "position_samples",
                ("kill_id", "round_id", "t_round_ms", "player_id", "side", "x", "y", "nx", "ny", "view_rad"),
                (
                    (kill_id(round_id(match_id, r.number), k.seq), round_id(match_id, r.number),
                     k.t_round_ms, players[p.puuid], p.side, p.x, p.y, p.nx, p.ny, p.view_rad)
                    for r in match.rounds
                    for k in r.kills
                    for p in k.positions
                ),
            )
        return match_id

    def finalize_series(self) -> list[Issue]:
        self.conn.execute(
            """UPDATE analytics.series s SET winner_team_id = w.team_id
               FROM (
                   SELECT DISTINCT ON (series_id) series_id, winner_team_id AS team_id
                   FROM analytics.matches
                   GROUP BY series_id, winner_team_id
                   ORDER BY series_id, count(*) DESC
               ) w
               WHERE s.id = w.series_id"""
        )
        rows = self.conn.execute(
            """SELECT s.number, st.slug, t.slug, count(DISTINCT LEAST(m.red_team_id, m.blue_team_id)
                      || '-' || GREATEST(m.red_team_id, m.blue_team_id))
               FROM analytics.series s
               JOIN analytics.stages st ON st.id = s.stage_id
               JOIN analytics.tournaments t ON t.id = st.tournament_id
               JOIN analytics.matches m ON m.series_id = s.id
               GROUP BY s.id, s.number, st.slug, t.slug
               HAVING count(DISTINCT LEAST(m.red_team_id, m.blue_team_id)
                      || '-' || GREATEST(m.red_team_id, m.blue_team_id)) > 1"""
        ).fetchall()
        return [
            Issue("warning", "series_mixed_teams", None, f"{t}/{st} série {n}: {c} confrontos diferentes")
            for n, st, t, c in rows
        ]
