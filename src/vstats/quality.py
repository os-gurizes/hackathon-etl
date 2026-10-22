from dataclasses import dataclass
from typing import Literal

Severity = Literal["info", "warning", "error"]


@dataclass(frozen=True, slots=True)
class Issue:
    severity: Severity
    code: str
    source_file: str | None
    detail: str
