import json
import os
from pathlib import Path

import psycopg
import pytest

from tests.factory import BLUE, RED, kill, match, round_result
from vstats.economy.build import build_economy
from vstats.geometry.build import build_geometry
from vstats.ingest import ingest
from vstats.load.migrate import apply_migrations
from vstats.metrics.build import build_stats
from vstats.models.win_probability import FEATURES, build_dataset
from vstats.positioning.heatmap import build_heatmaps
from vstats.reference.resolver import load_reference

TEST_DATABASE_URL = os.environ.get("VSTATS_TEST_DATABASE_URL", "postgresql:///vstats_test")
TABLES = ("matches", "match_players", "rounds", "round_players", "kills", "kill_assists", "position_samples")

pytestmark = pytest.mark.db


@pytest.fixture
def conn():
    try:
        connection = psycopg.connect(TEST_DATABASE_URL, autocommit=True)
    except psycopg.OperationalError:
        pytest.skip("Postgres de teste indisponível")
    connection.execute("DROP SCHEMA IF EXISTS analytics CASCADE")
    connection.execute("DROP TABLE IF EXISTS public.vstats_migrations")
    apply_migrations(connection)
    yield connection
    connection.close()


@pytest.fixture
def dataset(tmp_path: Path) -> Path:
    rounds = [
        round_result(0, "Red", "Attacker", [kill(10_000, RED[0], BLUE[0], assistants=(RED[1],), alive=(*RED, *BLUE[1:]))]),
        round_result(1, "Red", "Defender", [kill(5_000, BLUE[1], RED[2])], code="", result="Round timer expired"),
    ]
    folder = tmp_path / "Univavá" / "Fase de Grupos"
    folder.mkdir(parents=True)
    name = "UNIVAVA_G_001a_19-09-26_team_one_2_x_0_team_two_ascent.json"
    (folder / name).write_text(json.dumps(match(rounds, 2, 0)))
    (folder / "UNIVAVA_G_002_19-09-26_broken.json").write_text("{}")
    return tmp_path


def counts(conn: psycopg.Connection) -> dict[str, int]:
    return {t: conn.execute(f"SELECT count(*) FROM analytics.{t}").fetchone()[0] for t in TABLES}


def test_ingest_is_idempotent(conn: psycopg.Connection, dataset: Path) -> None:
    first = ingest(conn, dataset, load_reference())
    before = counts(conn)
    second = ingest(conn, dataset, load_reference())
    assert (first.loaded, first.skipped) == (1, 1)
    assert counts(conn) == before
    assert before["kills"] == 2 and before["kill_assists"] == 1 and before["position_samples"] == 10
    assert second.run_id == first.run_id + 1


def test_round_and_kill_ids_are_deterministic(conn: psycopg.Connection, dataset: Path) -> None:
    ingest(conn, dataset, load_reference())
    match_id = conn.execute("SELECT id FROM analytics.matches").fetchone()[0]
    kill_ids = [row[0] for row in conn.execute("SELECT id FROM analytics.kills ORDER BY id")]
    assert kill_ids == [match_id * 10_000, (match_id * 100 + 1) * 100]


def test_puuid_never_stored_in_clear(conn: psycopg.Connection, dataset: Path) -> None:
    ingest(conn, dataset, load_reference())
    hashes = {row[0] for row in conn.execute("SELECT puuid_hash FROM analytics.players")}
    assert len(hashes) == 10 and not hashes & set(RED + BLUE)


def test_quality_report_records_broken_file(conn: psycopg.Connection, dataset: Path) -> None:
    ingest(conn, dataset, load_reference())
    codes = {row[0] for row in conn.execute("SELECT code FROM analytics.data_quality_report")}
    assert {"FilenameError", "timeout_rounds"} <= codes


def test_geometry_assigns_zone_to_every_position(conn: psycopg.Connection, dataset: Path) -> None:
    ingest(conn, dataset, load_reference())
    [result] = build_geometry(conn)
    assert result.zone_source == "callout" and result.zones >= 1 and result.quality == "low"
    missing = conn.execute(
        "SELECT count(*) FROM analytics.position_samples WHERE zone_id IS NULL OR nx IS NULL"
    ).fetchone()[0]
    assert missing == 0
    assert conn.execute("SELECT count(*) FROM analytics.kills WHERE victim_zone_id IS NULL").fetchone()[0] == 0


def test_heatmap_totals_match_events(conn: psycopg.Connection, dataset: Path) -> None:
    ingest(conn, dataset, load_reference())
    build_geometry(conn)
    build_heatmaps(conn)
    for table in ("heatmap_cells", "heatmap_zones"):
        presence, kills, deaths, first_kills, traded = conn.execute(
            f"SELECT sum(presence), sum(kills), sum(deaths), sum(first_kills), sum(traded_deaths) FROM analytics.{table}"
        ).fetchone()
        assert (presence, kills, deaths, first_kills, traded) == (10, 2, 2, 2, 0)


def test_economy_classifies_buys_and_flags_broken_economy(conn: psycopg.Connection, tmp_path: Path) -> None:
    def team(red: int, blue: int) -> dict[str, int]:
        return {p: red for p in RED} | {p: blue for p in BLUE}

    rounds = [
        round_result(0, "Red", "Attacker", [], loadout=team(800, 800)),
        round_result(1, "Red", "Attacker", [], loadout=team(3900, 3000)),
        round_result(2, "Red", "Attacker", [], loadout=team(4500, 800)),
        round_result(3, "Red", "Attacker", [], loadout=team(4500, 4500)),
    ]
    folder = tmp_path / "UNIVAVA_G"
    folder.mkdir()
    (folder / "UNIVAVA_G_001_19-09-26_team_one_4_x_0_team_two_ascent.json").write_text(json.dumps(match(rounds, 4, 0)))
    ingest(conn, tmp_path, load_reference())
    build_stats(conn)
    build_economy(conn)
    buys = conn.execute(
        """SELECT e.number, t.slug, e.buy_type FROM analytics.round_team_economy e
           JOIN analytics.teams t ON t.id = e.team_id ORDER BY 1, 2"""
    ).fetchall()
    assert [b[2] for b in buys] == ["pistol", "pistol", "half_buy", "half_buy", "full_buy", "eco", "full_buy", "full_buy"]
    flags = conn.execute(
        """SELECT f.flag, t.slug, f.won FROM analytics.economy_flags f JOIN analytics.teams t ON t.id = f.team_id"""
    ).fetchall()
    assert ("broken_economy", "team_two", False) in flags


def test_win_probability_states_follow_kills_and_score(conn: psycopg.Connection, dataset: Path) -> None:
    ingest(conn, dataset, load_reference())
    data = build_dataset(conn)
    events = [(s.event, s.attack_alive, s.defense_alive) for s in data.states]
    assert events == [("start", 5, 5), ("kill", 5, 4), ("start", 5, 5), ("kill", 5, 4)]
    score_columns = [FEATURES.index("attack_score"), FEATURES.index("defense_score")]
    assert data.features[2, score_columns].tolist() == [0.0, 1.0]
    assert data.label.tolist() == [1, 1, 0, 0]
