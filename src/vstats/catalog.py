from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Tournament:
    slug: str
    name: str


@dataclass(frozen=True, slots=True)
class Stage:
    tournament: Tournament
    slug: str
    name: str
    order: int


RUSH_ESQUENTA = Tournament("rush-series-esquenta", "Rush Series Esquenta")
RUSH_ESQUENTA_2 = Tournament("rush-series-esquenta-2", "Rush Series Esquenta 2")
RUSH_INCLUSIVO = Tournament("rush-series-inclusivo", "Rush Series Inclusivo")
UNIVAVA = Tournament("univava", "Univavá")

STAGES: dict[str, Stage] = {
    "RUSHE": Stage(RUSH_ESQUENTA, "etapa-unica", "Etapa única", 1),
    "RUSH2": Stage(RUSH_ESQUENTA_2, "etapa-unica", "Etapa única", 1),
    "RUSH_INCLUSIVO": Stage(RUSH_INCLUSIVO, "etapa-unica", "Etapa única", 1),
    "UNIVAVA_C1": Stage(UNIVAVA, "classificatoria-1", "Classificatória 1", 1),
    "UNIVAVA_C2": Stage(UNIVAVA, "classificatoria-2", "Classificatória 2", 2),
    "UNIVAVA_C3": Stage(UNIVAVA, "classificatoria-3", "Classificatória 3", 3),
    "UNIVAVA_C4": Stage(UNIVAVA, "classificatoria-4", "Classificatória 4", 4),
    "UNIVAVA_G": Stage(UNIVAVA, "fase-de-grupos", "Fase de Grupos", 5),
}
