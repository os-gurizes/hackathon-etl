from collections import Counter
from pathlib import Path
from typing import Annotated

import psycopg
import typer

from vstats.config import DATABASE_URL
from vstats.economy.build import build_economy
from vstats.geometry.build import build_geometry
from vstats.geometry.preview import render_map_svgs
from vstats.ingest import ingest
from vstats.load.migrate import apply_migrations
from vstats.metrics.build import build_stats
from vstats.models.strategies import build_strategies
from vstats.models.win_probability import train_win_probability
from vstats.positioning.heatmap import build_heatmaps
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


@app.command()
def geometry(database_url: DatabaseOption = DATABASE_URL) -> None:
    """Gera silhueta, sites e zonas de cada mapa e marca a zona de cada posição."""
    with psycopg.connect(database_url, autocommit=True) as conn:
        apply_migrations(conn)
        results = build_geometry(conn)
    for r in results:
        typer.echo(
            f"{r.name:<10} amostras {r.sample_size:>6}  silhueta {r.quality:<3}  "
            f"zonas {r.zones:>2} ({r.zone_source})  sites {','.join(r.sites)}"
        )


@app.command()
def heatmap(database_url: DatabaseOption = DATABASE_URL) -> None:
    """Agrega presença, kills e mortes por célula e por zona."""
    with psycopg.connect(database_url, autocommit=True) as conn:
        apply_migrations(conn)
        cells, zones = build_heatmaps(conn)
    typer.echo(f"heatmap: {cells} linhas de célula, {zones} linhas de zona")


@app.command()
def stats(database_url: DatabaseOption = DATABASE_URL) -> None:
    """Calcula estatísticas por round, partida, arma e agente."""
    with psycopg.connect(database_url, autocommit=True) as conn:
        apply_migrations(conn)
        counts = build_stats(conn)
    typer.echo("  ".join(f"{table}: {count}" for table, count in counts.items()))


@app.command()
def economy(database_url: DatabaseOption = DATABASE_URL) -> None:
    """Classifica a compra de cada time por round e marca decisões econômicas prejudiciais."""
    with psycopg.connect(database_url, autocommit=True) as conn:
        apply_migrations(conn)
        counts = build_economy(conn)
    typer.echo("  ".join(f"{table}: {count}" for table, count in counts.items()))


@app.command("win-probability")
def win_probability(database_url: DatabaseOption = DATABASE_URL) -> None:
    """Treina o modelo de probabilidade de vitória por estado do round e calcula o impacto de cada kill."""
    with psycopg.connect(database_url, autocommit=True) as conn:
        apply_migrations(conn)
        report = train_win_probability(conn)
    typer.echo(f"run {report.run_id}: {report.states} estados, escolhido {report.chosen}")
    for name, values in report.metrics.items():
        typer.echo(f"  {name:<18} " + "  ".join(f"{k} {v}" for k, v in values.items()))
    for tournament, values in report.holdout.items():
        typer.echo(f"  holdout torneio {tournament}: " + "  ".join(f"{k} {v}" for k, v in values.items()))


@app.command()
def strategies(database_url: DatabaseOption = DATABASE_URL) -> None:
    """Agrupa os setups de cada time por mapa e lado e mede a taxa de sucesso."""
    with psycopg.connect(database_url, autocommit=True) as conn:
        apply_migrations(conn)
        summaries = build_strategies(conn)
    for s in summaries:
        typer.echo(f"mapa {s.map_id:>2} {s.side:<7} rounds {s.rounds:>5}  estratégias {s.clusters:>2}  sem padrão {s.noise_share:.0%}")


@app.command("all")
def run_all(
    source: Annotated[Path, typer.Argument(exists=True, help="pasta com os JSONs ou arquivo .zip")],
    database_url: DatabaseOption = DATABASE_URL,
) -> None:
    """Roda o pipeline completo."""
    ingest_command(source, database_url)
    geometry(database_url)
    heatmap(database_url)
    stats(database_url)
    economy(database_url)
    win_probability(database_url)
    strategies(database_url)


@app.command("export-maps")
def export_maps(
    out: Annotated[Path, typer.Argument(help="pasta de saída dos SVGs")],
    database_url: DatabaseOption = DATABASE_URL,
) -> None:
    """Exporta cada mapa como SVG (silhueta, zonas e sites) para revisão visual."""
    out.mkdir(parents=True, exist_ok=True)
    with psycopg.connect(database_url) as conn:
        for slug, svg in render_map_svgs(conn):
            (out / f"{slug}.svg").write_text(svg, encoding="utf-8")
            typer.echo(out / f"{slug}.svg")
