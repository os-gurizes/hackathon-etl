from datetime import date

import pytest

from vstats.raw.filename import FilenameError, parse_filename


@pytest.mark.parametrize(
    ("name", "tournament", "stage", "number", "letter"),
    [
        ("RUSHE_010_06-06-26_a2e_uff_8_x_13_azure_bears_golden_split.json", "rush-series-esquenta", "etapa-unica", 10, ""),
        ("RUSH2_030b_21-06-26_azure_bears_golden_13_x_11_ufmt_turuna_ascent.json", "rush-series-esquenta-2", "etapa-unica", 30, "b"),
        ("RUSH_INCLUSIVO_014a_08-08-26_caap_auroras_4_x_13_macklogic_rainbow_split.json", "rush-series-inclusivo", "etapa-unica", 14, "a"),
        ("UNIVAVA_G_003b_19-09-26_wolf_gaming_14_x_12_azure_bears_black_abyss.json", "univava", "fase-de-grupos", 3, "b"),
        ("UNIVAVA_C1_001_01-08-26_ufu_saints_13_x_2_usp_stars_lotus.json", "univava", "classificatoria-1", 1, ""),
    ],
)
def test_parses_every_prefix(name: str, tournament: str, stage: str, number: int, letter: str) -> None:
    parsed = parse_filename(name)
    assert parsed.stage.tournament.slug == tournament
    assert parsed.stage.slug == stage
    assert parsed.series_number == number
    assert parsed.game_letter == letter


def test_extracts_teams_scores_date_and_map() -> None:
    parsed = parse_filename("UNIVAVA_G_002a_19-09-26_ceub_octopus_13_x_0_ceub_octopus_vulgaris_sunset.json")
    assert (parsed.team_a, parsed.score_a) == ("ceub_octopus", 13)
    assert (parsed.team_b, parsed.score_b) == ("ceub_octopus_vulgaris", 0)
    assert parsed.played_on == date(2026, 9, 19)
    assert parsed.map_slug == "sunset"


@pytest.mark.parametrize(
    "name",
    ["XYZ_001_01-01-26_a_13_x_1_b_ascent.json", "RUSHE_001_a_13_x_1_b_ascent.json", "notes.json"],
)
def test_rejects_invalid_names(name: str) -> None:
    with pytest.raises(FilenameError):
        parse_filename(name)
