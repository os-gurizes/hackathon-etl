from pathlib import Path

import psycopg

from vstats.config import MIGRATIONS_DIR


def apply_migrations(conn: psycopg.Connection, directory: Path = MIGRATIONS_DIR) -> list[str]:
    conn.execute("CREATE TABLE IF NOT EXISTS public.vstats_migrations (name text PRIMARY KEY)")
    applied = {row[0] for row in conn.execute("SELECT name FROM public.vstats_migrations")}
    executed: list[str] = []
    for file in sorted(directory.glob("*.sql")):
        if file.name in applied:
            continue
        with conn.transaction():
            conn.execute(file.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO public.vstats_migrations (name) VALUES (%s)", (file.name,))
        executed.append(file.name)
    return executed
