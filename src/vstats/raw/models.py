from pydantic import BaseModel, ConfigDict, Field


class RawModel(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class Location(RawModel):
    x: int
    y: int


class PlayerLocation(RawModel):
    puuid: str
    view_radians: float = Field(alias="viewRadians")
    location: Location


class FinishingDamage(RawModel):
    damage_type: str = Field(alias="damageType")
    damage_item: str = Field(alias="damageItem")
    is_secondary_fire_mode: bool = Field(alias="isSecondaryFireMode")


class Kill(RawModel):
    time_since_game_start_millis: int = Field(alias="timeSinceGameStartMillis")
    time_since_round_start_millis: int = Field(alias="timeSinceRoundStartMillis")
    killer: str | None
    victim: str
    victim_location: Location = Field(alias="victimLocation")
    assistants: list[str]
    player_locations: list[PlayerLocation] = Field(alias="playerLocations")
    finishing_damage: FinishingDamage = Field(alias="finishingDamage")


class Damage(RawModel):
    receiver: str
    damage: int
    legshots: int
    bodyshots: int
    headshots: int


class Economy(RawModel):
    loadout_value: int = Field(alias="loadoutValue")
    weapon: str
    armor: str
    remaining: int
    spent: int


class RoundPlayerStats(RawModel):
    puuid: str
    kills: list[Kill]
    damage: list[Damage]
    score: int
    economy: Economy


class RoundResult(RawModel):
    round_num: int = Field(alias="roundNum")
    round_result: str = Field(alias="roundResult")
    round_ceremony: str = Field(alias="roundCeremony", default="")
    round_result_code: str = Field(alias="roundResultCode")
    winning_team: str = Field(alias="winningTeam")
    winning_team_role: str = Field(alias="winningTeamRole")
    bomb_planter: str | None = Field(alias="bombPlanter")
    bomb_defuser: str | None = Field(alias="bombDefuser")
    plant_round_time: int = Field(alias="plantRoundTime")
    plant_location: Location = Field(alias="plantLocation")
    plant_site: str = Field(alias="plantSite")
    defuse_round_time: int = Field(alias="defuseRoundTime")
    defuse_location: Location = Field(alias="defuseLocation")
    player_stats: list[RoundPlayerStats] = Field(alias="playerStats")


class AbilityCasts(RawModel):
    grenade_casts: int = Field(alias="grenadeCasts")
    ability1_casts: int = Field(alias="ability1Casts")
    ability2_casts: int = Field(alias="ability2Casts")
    ultimate_casts: int = Field(alias="ultimateCasts")


class PlayerStats(RawModel):
    score: int
    rounds_played: int = Field(alias="roundsPlayed")
    kills: int
    deaths: int
    assists: int
    ability_casts: AbilityCasts | None = Field(alias="abilityCasts", default=None)


class Player(RawModel):
    puuid: str
    game_name: str = Field(alias="gameName")
    tag_line: str = Field(alias="tagLine")
    team_id: str = Field(alias="teamId")
    character_id: str | None = Field(alias="characterId")
    stats: PlayerStats | None = None
    is_observer: bool = Field(alias="isObserver")


class Team(RawModel):
    team_id: str = Field(alias="teamId")
    won: bool
    rounds_played: int = Field(alias="roundsPlayed")
    rounds_won: int = Field(alias="roundsWon")


class MatchInfo(RawModel):
    match_id: str = Field(alias="matchId")
    map_id: str = Field(alias="mapId")
    game_version: str = Field(alias="gameVersion")
    game_length_millis: int = Field(alias="gameLengthMillis")
    game_start_millis: int = Field(alias="gameStartMillis")
    is_completed: bool = Field(alias="isCompleted")


class RawMatch(RawModel):
    match_info: MatchInfo = Field(alias="matchInfo")
    players: list[Player]
    teams: list[Team]
    round_results: list[RoundResult] = Field(alias="roundResults")
