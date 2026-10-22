import re
from dataclasses import dataclass
from datetime import date

from vstats.catalog import STAGES, Stage

_PATTERN = re.compile(
    r"^(?P<prefix>[A-Z0-9_]+?)_(?P<number>\d+)(?P<game>[a-z]?)_"
    r"(?P<day>\d{2})-(?P<month>\d{2})-(?P<year>\d{2})_"
    r"(?P<team_a>[a-z0-9_]+?)_(?P<score_a>\d+)_x_(?P<score_b>\d+)_(?P<team_b>[a-z0-9_]+)_"
    r"(?P<map>[a-z]+)\.json$"
)


class FilenameError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class MatchFilename:
    stage: Stage
    series_number: int
    game_letter: str
    played_on: date
    team_a: str
    score_a: int
    team_b: str
    score_b: int
    map_slug: str


def parse_filename(name: str) -> MatchFilename:
    match = _PATTERN.match(name)
    if match is None:
        raise FilenameError(f"nome fora do padrão: {name}")
    stage = STAGES.get(match["prefix"])
    if stage is None:
        raise FilenameError(f"prefixo desconhecido: {match['prefix']}")
    return MatchFilename(
        stage=stage,
        series_number=int(match["number"]),
        game_letter=match["game"],
        played_on=date(2000 + int(match["year"]), int(match["month"]), int(match["day"])),
        team_a=match["team_a"],
        score_a=int(match["score_a"]),
        team_b=match["team_b"],
        score_b=int(match["score_b"]),
        map_slug=match["map"],
    )
