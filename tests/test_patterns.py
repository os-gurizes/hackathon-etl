import numpy as np
import pytest

from vstats.models.patterns import Finding, benjamini_hochberg, binomial_p, normalized_entropy, watch_tier


def test_benjamini_hochberg_matches_reference_values() -> None:
    adjusted = benjamini_hochberg(np.array([0.01, 0.04, 0.03, 0.20]))
    assert adjusted.tolist() == pytest.approx([0.04, 0.0533333, 0.0533333, 0.20], rel=1e-4)
    assert benjamini_hochberg(np.array([])).size == 0


def test_binomial_p_is_small_only_when_occurrences_exceed_expected() -> None:
    assert binomial_p(10, 20, 0.1) < 0.001
    assert binomial_p(2, 20, 0.1) > 0.5
    assert binomial_p(1, 10, 0.0) < 1e-6


def test_entropy_is_normalized_by_zones_on_the_map() -> None:
    assert normalized_entropy([3, 3, 3, 3], 4) == 0.0
    assert normalized_entropy([1, 2, 3, 4], 4) == pytest.approx(1.0)
    assert 0 < normalized_entropy([1, 1, 1, 2], 4) < 1
    spread = [1, 2, 3, 4, 5, 6] * 3
    assert normalized_entropy(spread, 24) == pytest.approx(normalized_entropy(spread * 10, 24))


def finding(occurrences: int, expected: float, p_value: float, cost: float) -> Finding:
    return Finding(1, 1, "attack", "isolated_death", None, 40, occurrences, expected, 0.1, p_value, cost, [])


def test_watch_tier_requires_strong_evidence_and_cost() -> None:
    assert watch_tier(finding(12, 4.0, 0.001, 1.2)) == "watch"
    assert watch_tier(finding(12, 4.0, 0.03, 1.2)) is None
    assert watch_tier(finding(5, 4.0, 0.001, 1.2)) is None
    assert watch_tier(finding(12, 4.0, 0.001, 0.2)) is None
