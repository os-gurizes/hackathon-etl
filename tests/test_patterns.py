import numpy as np
import pytest

from vstats.models.patterns import benjamini_hochberg, binomial_p, normalized_entropy


def test_benjamini_hochberg_matches_reference_values() -> None:
    adjusted = benjamini_hochberg(np.array([0.01, 0.04, 0.03, 0.20]))
    assert adjusted.tolist() == pytest.approx([0.04, 0.0533333, 0.0533333, 0.20], rel=1e-4)
    assert benjamini_hochberg(np.array([])).size == 0


def test_binomial_p_is_small_only_when_occurrences_exceed_expected() -> None:
    assert binomial_p(10, 20, 0.1) < 0.001
    assert binomial_p(2, 20, 0.1) > 0.5
    assert binomial_p(1, 10, 0.0) < 1e-6


def test_entropy_is_zero_for_single_zone_and_one_when_uniform() -> None:
    assert normalized_entropy([3, 3, 3, 3]) == 0.0
    assert normalized_entropy([1, 2, 3, 4]) == pytest.approx(1.0)
    assert 0 < normalized_entropy([1, 1, 1, 2]) < 1
