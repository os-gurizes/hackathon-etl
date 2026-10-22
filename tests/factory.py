from typing import Any

VANDAL = "9C82E19D-4575-0200-1A81-3EACF00CF872"
CLASSIC = "29A0CFAB-485B-F5D5-779A-B59F85E204A8"
HEAVY_ARMOR = "822BCAB2-40A2-324E-C137-E09195AD7692"
JETT = "add6443a-41bd-e414-f6ad-e58d267f4e95"

RED = [f"red-{i}" for i in range(5)]
BLUE = [f"blue-{i}" for i in range(5)]


def kill(
    t: int,
    killer: str | None,
    victim: str,
    *,
    damage_type: str = "Weapon",
    item: str = VANDAL,
    assistants: tuple[str, ...] = (),
    killer_at: tuple[int, int] = (0, 0),
    victim_at: tuple[int, int] = (300, 400),
    alive: tuple[str, ...] = (),
) -> dict[str, Any]:
    locations = [
        {"puuid": puuid, "viewRadians": 1.0, "location": {"x": i * 10, "y": i * 10}}
        for i, puuid in enumerate(alive)
        if puuid != killer
    ]
    if killer is not None and killer != victim:
        locations.append(
            {"puuid": killer, "viewRadians": 0.5, "location": {"x": killer_at[0], "y": killer_at[1]}}
        )
    return {
        "timeSinceGameStartMillis": t + 100_000,
        "timeSinceRoundStartMillis": t,
        "killer": killer,
        "victim": victim,
        "victimLocation": {"x": victim_at[0], "y": victim_at[1]},
        "assistants": list(assistants),
        "playerLocations": locations,
        "finishingDamage": {"damageType": damage_type, "damageItem": item, "isSecondaryFireMode": False},
    }


def round_result(
    number: int,
    winner: str,
    winner_role: str,
    kills: list[dict[str, Any]],
    *,
    code: str = "Elimination",
    result: str = "Eliminated",
    planter: str | None = None,
    plant_site: str = "",
    damage: dict[str, list[dict[str, Any]]] | None = None,
    loadout: dict[str, int] | None = None,
) -> dict[str, Any]:
    by_killer: dict[str, list[dict[str, Any]]] = {puuid: [] for puuid in RED + BLUE}
    for item in kills:
        owner = item["killer"] or item["victim"]
        by_killer[owner].append(item)
    return {
        "roundNum": number,
        "roundResult": result,
        "roundCeremony": "CeremonyDefault",
        "winningTeam": winner,
        "winningTeamRole": winner_role,
        "bombPlanter": planter,
        "bombDefuser": None,
        "plantRoundTime": 40_000 if planter else 0,
        "plantLocation": {"x": 1000, "y": 2000} if planter else {"x": 0, "y": 0},
        "plantSite": plant_site,
        "defuseRoundTime": 0,
        "defuseLocation": {"x": 0, "y": 0},
        "playerStats": [
            {
                "puuid": puuid,
                "kills": by_killer[puuid],
                "damage": (damage or {}).get(puuid, []),
                "score": 100,
                "economy": {
                    "loadoutValue": (loadout or {}).get(puuid, 3900),
                    "weapon": VANDAL,
                    "armor": HEAVY_ARMOR,
                    "remaining": 500,
                    "spent": 3900,
                },
                "ability": {},
            }
            for puuid in RED + BLUE
        ],
        "roundResultCode": code,
    }


def match(rounds: list[dict[str, Any]], red_won: int, blue_won: int, *, observer: bool = False) -> dict[str, Any]:
    kills: dict[str, int] = {p: 0 for p in RED + BLUE}
    deaths: dict[str, int] = {p: 0 for p in RED + BLUE}
    assists: dict[str, int] = {p: 0 for p in RED + BLUE}
    team = {p: "Red" for p in RED} | {p: "Blue" for p in BLUE}
    for round_ in rounds:
        for stats in round_["playerStats"]:
            for item in stats["kills"]:
                killer, victim = item["killer"], item["victim"]
                if killer and killer != victim and team[killer] != team[victim]:
                    kills[killer] += 1
                if item["finishingDamage"]["damageType"] != "Bomb":
                    deaths[victim] += 1
                for assistant in item["assistants"]:
                    assists[assistant] += 1
    players = [
        {
            "puuid": puuid,
            "gameName": puuid.upper(),
            "tagLine": "BR1",
            "teamId": team[puuid],
            "characterId": JETT,
            "isObserver": False,
            "stats": {
                "score": 1000,
                "roundsPlayed": len(rounds),
                "kills": kills[puuid],
                "deaths": deaths[puuid],
                "assists": assists[puuid],
                "abilityCasts": {"grenadeCasts": 1, "ability1Casts": 2, "ability2Casts": 3, "ultimateCasts": 0},
            },
        }
        for puuid in RED + BLUE
    ]
    if observer:
        players.append(
            {"puuid": "obs", "gameName": "OBS", "tagLine": "1", "teamId": "Neutral",
             "characterId": None, "isObserver": True, "stats": None}
        )
    return {
        "matchInfo": {
            "matchId": "00000000-0000-0000-0000-000000000001",
            "mapId": "/Game/Maps/Ascent/Ascent",
            "gameVersion": "release-13.05-shipping",
            "gameLengthMillis": 1_800_000,
            "gameStartMillis": 1_786_213_013_228,
            "isCompleted": True,
        },
        "players": players,
        "teams": [
            {"teamId": "Red", "won": red_won > blue_won, "roundsPlayed": len(rounds), "roundsWon": red_won},
            {"teamId": "Blue", "won": blue_won > red_won, "roundsPlayed": len(rounds), "roundsWon": blue_won},
        ],
        "roundResults": rounds,
    }
