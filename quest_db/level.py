from typing import Dict, List, NamedTuple, Optional

import requests

LevelNameType = str
PlayerNameType = str

LEVEL_NAMES: List[LevelNameType] = [
    "total",
    "attack",
    "defence",
    "strength",
    "hitpoints",
    "ranged",
    "prayer",
    "magic",
    "cooking",
    "woodcutting",
    "fletching",
    "fishing",
    "firemaking",
    "crafting",
    "smithing",
    "mining",
    "herblore",
    "agility",
    "thieving",
    "slayer",
    "farming",
    "runecraft",
    "hunter",
    "construction",
]


class LevelMetadata(NamedTuple):
    """Represents level data for a player"""

    rank: int
    level: int
    experience: Optional[int] = None

    @classmethod
    def from_entry(cls, entry: str) -> "LevelMetadata":
        """Builds level metadata from a comma-separated string of integers"""
        return cls(*[int(p) for p in entry.split(",")])


def get_levels(player: PlayerNameType) -> Dict[LevelNameType, LevelMetadata]:
    data = requests.get(
        f"https://secure.runescape.com/m=hiscore_oldschool/index_lite.ws?player={player}"
    ).text

    levels = {}
    counter = 0
    for line in data.split("\n"):
        line = line.strip()
        if not line:
            continue

        metadata = LevelMetadata.from_entry(line)
        if metadata.experience is None:
            continue

        levels[LEVEL_NAMES[counter]] = metadata
        counter += 1

    return levels
