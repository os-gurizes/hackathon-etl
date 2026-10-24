import re

from vstats.insights import templates as t

DASHES = re.compile("[–—]")


def test_numbers_use_brazilian_format() -> None:
    assert t.number(1.25, 2) == "1,25"
    assert t.percent(0.384) == "38%"
    assert t.percent(0.034) == "3,4%" and t.percent(0.004) == "0,4%" and t.percent(0.0) == "0%"
    assert t.rounds_text(1.04) == "1,0 round"
    assert t.rounds_text(2.75) == "2,8 rounds"
    assert t.times(1) == "1 vez" and t.times(3) == "3 vezes"


def test_severity_follows_cost() -> None:
    assert [t.severity_for_cost(c) for c in (0.4, 1.2, 3.0)] == [1, 2, 3]


def test_templates_have_no_dashes_or_jargon() -> None:
    texts = [
        *t.first_death_zone("Ascent", "attack", "Principal A", 0.38, 0.14, 1.6, 12),
        *t.isolated_death("Lotus", "defense", 0.52, 0.34, 2.8, 8),
        *t.predictable_route("Haven", "attack", 0.3, 0.12, 1.1),
        *t.repeat_after_first_death("Split", "defense", 4, 0.7),
        *t.pressure_drop("disadvantage", 0.38, 0.54, 0.8),
        *t.clutch_strength(9, 31, 0.29, 0.14),
        *t.rotation_without_info(157, 0.1, 0.04),
        *t.overuse(6, 20),
        *t.ult_in_decided_rounds(4, 12),
        *t.strategy("Ascent", "attack", "Execução rápida no B", 0.62, 42, True),
        *t.combo("a", "b", "Ascent", 28, 0.86, 0.6),
        *t.best_agent("Neon", "Haven", 294, 203, 9),
        *t.best_map("Ascent", 1.05, 0.98, 12),
        *(text for title, text in t.ECONOMY.values()),
        *(text for title, text in t.TEAM_ECONOMY.values()),
        t.WATCH_NOTE,
    ]
    for text in texts:
        assert not DASHES.search(text)
        assert "p-valor" not in text and "significância" not in text


def test_first_death_zone_text() -> None:
    title, body = t.first_death_zone("Ascent", "attack", "Principal A", 0.384, 0.141, 1.56, 12)
    assert title == "Você morre primeiro em Principal A"
    assert body == (
        "No Ascent, no ataque, você é o primeiro do time a morrer em Principal A em 38% dos rounds. "
        "A média dos jogadores nessa zona é 14%. Em 12 partidas, isso custou cerca de 1,6 rounds."
    )
