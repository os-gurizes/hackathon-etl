from vstats.models.pressure import detect_rotations, event_contexts


def test_event_contexts() -> None:
    assert event_contexts(2, 4, False, 10_000, "defense") == {"disadvantage"}
    assert event_contexts(1, 3, True, 90_000, "attack") == {"disadvantage", "clutch", "post_plant"}
    assert event_contexts(4, 2, False, 80_000, "attack") == {"advantage", "low_clock"}
    assert event_contexts(4, 2, False, 80_000, "defense") == {"advantage"}
    assert event_contexts(3, 3, False, 5_000, "attack") == set()


def test_rotation_without_information() -> None:
    samples = [(10_000, "A"), (30_000, "B"), (40_000, "Meio")]
    assert detect_rotations(samples, site_events=[(35_000, "B")]) == [("A", "B", 10_000, 30_000, False)]


def test_rotation_with_information_before_leaving() -> None:
    samples = [(20_000, "B"), (35_000, "A")]
    assert detect_rotations(samples, site_events=[(15_000, "A")]) == [("B", "A", 20_000, 35_000, True)]


def test_rotation_through_mid_counts_from_last_site() -> None:
    samples = [(10_000, "A"), (20_000, "Meio"), (30_000, "B")]
    assert detect_rotations(samples, []) == [("A", "B", 10_000, 30_000, False)]


def test_staying_around_one_site_is_not_a_rotation() -> None:
    assert detect_rotations([(10_000, "A"), (20_000, "Meio"), (30_000, "A")], []) == []
