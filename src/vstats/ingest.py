from dataclasses import dataclass
from pathlib import Path

import psycopg
from pydantic import ValidationError

from vstats.config import PIPELINE_VERSION
from vstats.load.loader import Loader
from vstats.quality import Issue
from vstats.raw.filename import FilenameError, parse_filename
from vstats.raw.models import RawMatch
from vstats.raw.sources import iter_source_files
from vstats.reference.resolver import Reference
from vstats.transform import MatchError, MatchRecord, transform_match


@dataclass(frozen=True, slots=True)
class IngestSummary:
    run_id: int
    seen: int
    loaded: int
    skipped: int
    issues: tuple[Issue, ...]


def read_matches(path: Path, reference: Reference) -> tuple[list[tuple[MatchRecord, str]], list[Issue], int]:
    matches: list[tuple[MatchRecord, str]] = []
    issues: list[Issue] = []
    seen_uuids: dict[str, str] = {}
    seen = 0
    for source in iter_source_files(path):
        seen += 1
        try:
            meta = parse_filename(source.name)
            raw = RawMatch.model_validate_json(source.content)
            record = transform_match(raw, meta, reference, source.relative_path)
        except (FilenameError, MatchError, ValidationError) as error:
            issues.append(Issue("error", type(error).__name__, source.relative_path, str(error)[:500]))
            continue
        duplicate = seen_uuids.get(record.match_uuid)
        if duplicate is not None:
            issues.append(
                Issue("error", "duplicate_match", source.relative_path, f"mesmo matchId de {duplicate}")
            )
            continue
        seen_uuids[record.match_uuid] = source.relative_path
        matches.append((record, source.relative_path))
        issues.extend(record.issues)
    return matches, issues, seen


def ingest(conn: psycopg.Connection, path: Path, reference: Reference) -> IngestSummary:
    matches, issues, seen = read_matches(path, reference)
    loader = Loader(conn, reference)
    with conn.transaction():
        run_id = loader.start_run(str(path), PIPELINE_VERSION)
        loader.load_dimensions([record for record, _ in matches])
        for record, source_file in matches:
            loader.load_match(record, source_file)
        issues.extend(loader.finalize_series())
        issues.extend(
            Issue("warning", f"unresolved_{kind}", None, f"sem nome na referência: '{uuid}'")
            for kind, uuid in sorted(reference.unresolved)
        )
        loader.finish_run(run_id, seen, len(matches), seen - len(matches), issues)
    return IngestSummary(run_id, seen, len(matches), seen - len(matches), tuple(issues))
