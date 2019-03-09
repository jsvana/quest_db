from typing import Dict, List, NamedTuple, Optional

import requests

LevelNameType = str
PlayerNameType = str

LevelMetadata = Dict[str, Dict[str, int]]


def get_levels(player: PlayerNameType) -> Dict[LevelNameType, LevelMetadata]:
    response = requests.get(f"https://www.ge-tracker.com/api/hiscore/{player}").json()

    ret = {}
    for skill, stats in response["data"]["stats"].items():
        ret[skill] = {
            "rank": int(stats["rank"]),
            "exp": int(stats["exp"]),
            "level": int(stats["level"]),
        }
    return ret
