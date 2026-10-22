import pytest

from vstats.models.strategies import TeamRound, apportion, describe, setup_zones, wilson

REGION = {1: "A", 2: "A", 3: "B", 4: "Meio", 5: "Base"}
NAMES = {1: "Principal A", 2: "Ponto A", 3: "Principal B", 4: "Mercado do Meio", 5: "Surgimento no Lado Atacante"}


def team_round(zones: tuple[int, ...], *, side: str = "attack", won: bool = True,
               plant_site: str | None = "A", plant_time_ms: int | None = 30_000) -> TeamRound:
    return TeamRound(1, 1, 1, side, won, plant_site, plant_time_ms, zones)


def test_setup_zone_uses_latest_sample_inside_window_or_first_available() -> None:
    samples = [(5_000, 1), (20_000, 2), (50_000, 3)]
    assert setup_zones(samples, 30_000) == 2
    assert setup_zones([(60_000, 3), (45_000, 4)], 30_000) == 4
    assert setup_zones([], 30_000) is None


def test_apportion_keeps_team_size() -> None:
    assert apportion({"Meio": 4.4, "A": 1.5, "B": 0.1}, 5) == {"Meio": 4, "A": 1}
    assert sum(apportion({"A": 1.6, "B": 1.7, "Meio": 1.7}, 5).values()) == 5


def test_wilson_interval_contains_rate_and_narrows_with_samples() -> None:
    low_small, high_small = wilson(6, 10)
    low_big, high_big = wilson(600, 1000)
    assert low_small < 0.6 < high_small
    assert high_big - low_big < high_small - low_small
    assert wilson(0, 0) == (0.0, 0.0)


def test_describe_fast_execute() -> None:
    members = [team_round((1, 1, 2, 2, 4)) for _ in range(10)]
    info = describe(members, "attack", REGION, NAMES)
    assert info.title.startswith("Execução rápida no A")
    assert info.region_counts == {"A": 4, "Meio": 1}
    assert info.plant_sites == {"A": 1.0} and info.plant_time_s == 30.0


def test_describe_attack_without_plants() -> None:
    members = [team_round((3, 3, 3, 4, 5), plant_site=None, plant_time_ms=None) for _ in range(5)]
    assert "sem plant frequente" in describe(members, "attack", REGION, NAMES).title


@pytest.mark.parametrize(
    ("zones", "expected"),
    [((1, 1, 2, 3, 4), "Stack de 3 no A"), ((1, 2, 3, 3, 4), "Defesa 2 no A, 2 no B, 1 no Meio")],
)
def test_describe_defense(zones: tuple[int, ...], expected: str) -> None:
    info = describe([team_round(zones, side="defense", plant_site=None)] * 4, "defense", REGION, NAMES)
    assert info.title.startswith(expected)
