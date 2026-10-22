import os
from pathlib import Path

PIPELINE_VERSION = "0.1.0"
DATABASE_URL = os.environ.get("VSTATS_DATABASE_URL", "postgresql:///vstats")
MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"
