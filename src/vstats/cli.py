from collections import Counter
from pathlib import Path
from typing import Annotated

import psycopg
import typer

from vstats.config import DATABASE_URL
from vstats.ingest import ingest
from vstats.load.migrate import apply_migrations
from vstats.reference.resolver import load_reference

app = typer.Typer(no_args_is_help=True, add_completion=False)

DatabaseOption = Annotated[str, typer.Option("--database-url", envvar="VSTATS_DATABASE_URL")]


@app.command()
def migrate(database_url: DatabaseOption = DATABASE_URL) -> None:
    """Aplica as migrations pendentes do schema analytics."""
    with psycopg.connect(database_url, autocommit=True) as conn:
        executed = apply_migrations(conn)
    typer.echo(f"migrations aplicadas: {', '.join(executed) or 'nenhuma'}")


@app.command("ingest")
def ingest_command(
    source: Annotated[Path, typer.Argument(exists=True, help="pasta com os JSONs ou arquivo .zip")],
    database_url: DatabaseOption = DATABASE_URL,
) -> None:
    """Lê as partidas, valida e carrega no Postgres. Pode ser repetido sem duplicar dados."""
    with psycopg.connect(database_url, autocommit=True) as conn:
        apply_migrations(conn)
        summary = ingest(conn, source, load_reference())
    typer.echo(
        f"run {summary.run_id}: {summary.seen} arquivos, {summary.loaded} carregados, "
        f"{summary.skipped} ignorados"
    )
    for (severity, code), count in sorted(Counter((i.severity, i.code) for i in summary.issues).items()):
        typer.echo(f"  {severity:<7} {code:<24} {count}")


@app.command()
def quality(
    run_id: Annotated[int | None, typer.Option(help="padrão: último run")] = None,
    database_url: DatabaseOption = DATABASE_URL,
) -> None:
    """Mostra o relatório de qualidade de um run."""
    with psycopg.connect(database_url) as conn:
        rows = conn.execute(
            """SELECT severity, code, coalesce(source_file, '-'), detail
               FROM analytics.data_quality_report
               WHERE run_id = coalesce(%s, (SELECT max(id) FROM analytics.ingest_runs))
               ORDER BY CASE severity WHEN 'error' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, code""",
            (run_id,),
        ).fetchall()
    for severity, code, source_file, detail in rows:
        typer.echo(f"{severity:<7} {code:<24} {source_file}  {detail}")
