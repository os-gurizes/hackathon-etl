import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REFERENCE_DIR = Path(__file__).resolve().parents[3] / "reference"
SNAPSHOT_FILE = "valorant-api-13.08.json"
GIST_FILE = "gist-uuids.json"
OVERRIDES_FILE = "overrides.json"
TEAM_NAMES_FILE = "team-names.json"


@dataclass(frozen=True, slots=True)
class AgentRef:
    uuid: str
    name: str
    role: str | None
    abilities: dict[str, str]


@dataclass(frozen=True, slots=True)
class WeaponRef:
    uuid: str
    name: str
    category: str | None
    cost: int | None
    is_armor: bool


@dataclass(frozen=True, slots=True)
class Callout:
    region: str
    super_region: str
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class MapRef:
    internal_name: str
    name: str
    x_mult: float
    y_mult: float
    x_add: float
    y_add: float
    callouts: tuple[Callout, ...]

    def normalize(self, x: float, y: float) -> tuple[float, float]:
        return y * self.x_mult + self.x_add, x * self.y_mult + self.y_add


def unknown_name(uuid: str) -> str:
    return f"Desconhecido ({uuid[:8]})" if uuid else "Desconhecido"


@dataclass
class Reference:
    agents: dict[str, AgentRef]
    weapons: dict[str, WeaponRef]
    maps: dict[str, MapRef]
    team_names: dict[str, str]
    unresolved: set[tuple[str, str]] = field(default_factory=set)

    def agent(self, uuid: str) -> AgentRef:
        found = self.agents.get(uuid.lower())
        if found is None:
            self.unresolved.add(("agent", uuid))
            return AgentRef(uuid.lower(), unknown_name(uuid), None, {})
        return found

    def weapon(self, uuid: str) -> WeaponRef:
        found = self.weapons.get(uuid.lower())
        if found is None:
            self.unresolved.add(("weapon", uuid))
            return WeaponRef(uuid.lower(), unknown_name(uuid), None, None, False)
        return found

    def map(self, internal_name: str) -> MapRef | None:
        found = self.maps.get(internal_name)
        if found is None:
            self.unresolved.add(("map", internal_name))
        return found

    def team_name(self, slug: str) -> str:
        return self.team_names.get(slug) or slug.replace("_", " ").title()


def _read(directory: Path, name: str) -> Any:
    path = directory / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def load_reference(directory: Path = REFERENCE_DIR) -> Reference:
    snapshot = _read(directory, SNAPSHOT_FILE)
    gist = _read(directory, GIST_FILE)
    overrides = _read(directory, OVERRIDES_FILE)

    agents: dict[str, AgentRef] = {
        uuid.lower(): AgentRef(uuid.lower(), name.strip(), None, {})
        for uuid, name in gist.get("characters", {}).items()
    }
    for item in snapshot.get("agents", []):
        uuid = item["uuid"].lower()
        agents[uuid] = AgentRef(uuid, item["name"], item["role"], item["abilities"])
    for uuid, item in overrides.get("agents", {}).items():
        agents[uuid.lower()] = AgentRef(
            uuid.lower(), item["name"], item.get("role"), item.get("abilities", {})
        )

    weapons: dict[str, WeaponRef] = {
        uuid.lower(): WeaponRef(uuid.lower(), name.strip(), None, None, False)
        for uuid, name in gist.get("equips", {}).items()
    }
    for item in snapshot.get("weapons", []):
        uuid = item["uuid"].lower()
        weapons[uuid] = WeaponRef(uuid, item["name"], item["category"], item["cost"], False)
    for item in snapshot.get("gear", []):
        uuid = item["uuid"].lower()
        weapons[uuid] = WeaponRef(uuid, item["name"], "Armor", item["cost"], True)
    for section, is_armor in (("weapons", False), ("gear", True)):
        for uuid, item in overrides.get(section, {}).items():
            weapons[uuid.lower()] = WeaponRef(
                uuid.lower(), item["name"], item.get("category"), item.get("cost"), is_armor
            )

    maps = {
        item["internalName"]: MapRef(
            internal_name=item["internalName"],
            name=item["name"],
            x_mult=item["xMultiplier"],
            y_mult=item["yMultiplier"],
            x_add=item["xScalarToAdd"],
            y_add=item["yScalarToAdd"],
            callouts=tuple(
                Callout(c["region"], c["superRegion"], c["x"], c["y"]) for c in item["callouts"]
            ),
        )
        for item in snapshot.get("maps", [])
    }

    return Reference(agents, weapons, maps, _read(directory, TEAM_NAMES_FILE))
