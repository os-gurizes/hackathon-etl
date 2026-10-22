import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


@dataclass(frozen=True, slots=True)
class SourceFile:
    name: str
    relative_path: str
    content: bytes


def iter_source_files(path: Path) -> Iterator[SourceFile]:
    if path.is_dir():
        for file in sorted(path.rglob("*.json")):
            yield SourceFile(file.name, str(file.relative_to(path)), file.read_bytes())
        return
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            for info in sorted(archive.infolist(), key=lambda i: i.filename):
                inner = PurePosixPath(info.filename)
                if info.is_dir() or inner.suffix != ".json":
                    continue
                yield SourceFile(inner.name, info.filename, archive.read(info))
        return
    raise FileNotFoundError(f"esperado uma pasta ou um .zip: {path}")
