import json
import os
from pathlib import Path

import psycopg
import pytest

from tests.factory import BLUE, RED, kill, match, round_result
from vstats.ingest import ingest
from vstats.load.migrate import apply_migrations
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
