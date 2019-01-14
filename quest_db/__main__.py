import argparse
import json
import pathlib
import sys
from typing import Dict, List, NamedTuple

import requests
from bs4 import BeautifulSoup
from tabulate import tabulate

from .level import LevelNameType, get_levels


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--load-quest-data-from",
        type=pathlib.Path,
        help=(
            "Location to load quest data from (if not provided, "
            "data will be loaded from oldschool.runescape.wiki)"
        ),
    )
    parser.add_argument(
        "--dump-quest-data-to",
        type=pathlib.Path,
        help=("Location to dump quest data to"),
    )
    parser.add_argument(
        "--quests", nargs="+", metavar="QUEST_NAME", help="Only parse specific quests"
    )
    parser.add_argument("player", help="Player to query")
    return parser.parse_args()


class Quest:
    def __init__(
        self,
        number: float,
        title: str,
        slug: str,
        difficulty: str,
        length: str,
        quest_points: int,
        series: str,
    ) -> None:
        self.number = number
        self.title = title
        self.slug = slug
        self.difficulty = difficulty
        self.length = length
        self.quest_points = quest_points
        self.series = series

        self.__loaded = False
        self._requirements: Dict[LevelNameType, int] = {}

    @property
    def requirements(self) -> Dict[LevelNameType, int]:
        if not self.__loaded:
            self._load()

        return self._requirements

    def _load(self) -> None:
        if self.__loaded:
            return

        soup = BeautifulSoup(
            requests.get(f"https://oldschool.runescape.wiki{self.slug}").text,
            "html.parser",
        )
        for span in soup.find_all("span", class_="SkillClickPic"):
            parent = span.find_parent("td")
            if parent is None:
                continue
            text = span.get_text().strip()
            if not text:
                continue

            self._requirements[span.find("a")["title"].lower()] = int(text)

        self.__loaded = True


class QuestDatabase:
    def __init__(self, quest_data: List[Quest]) -> None:
        self.quests = quest_data

    @classmethod
    def from_web(self) -> "QuestDatabase":
        soup = BeautifulSoup(
            requests.get("https://oldschool.runescape.wiki/w/Quests/List").text,
            "html.parser",
        )

        all_quests: List[Quest] = []
        for row in soup.find_all("tr"):
            data_row = []
            for i, cell in enumerate(row.find_all("td")):
                text = cell.get_text().strip()

                if i == 0:
                    text = float(text)
                elif i == 4:
                    text = int(text)

                data_row.append(text)

                if i == 1:
                    data_row.append(cell.find("a").get("href"))

            if len(data_row) != 7:
                continue

            all_quests.append(Quest(*data_row))

        return QuestDatabase(all_quests)

    @classmethod
    def from_file(self, path: pathlib.Path) -> "QuestDatabase":
        with path.open("r") as f:
            json_quests = json.load(f)

        quests: List[Quest] = []
        for quest in json_quests:
            quests.append(
                Quest(
                    quest["number"],
                    quest["title"],
                    quest["slug"],
                    quest["difficulty"],
                    quest["length"],
                    quest["quest_points"],
                    quest["series"],
                )
            )
        return QuestDatabase(quests)

    def dump_to_file(self, path: pathlib.Path) -> None:
        with path.open("w") as f:
            json.dump([q._asdict() for q in self.quests], f, sort_keys=True, indent=4)


def main():
    args = parse_args()

    player_levels = get_levels(args.player)

    if args.load_quest_data_from:
        if not args.load_quest_data_from.is_file():
            print(
                f'Specified quest data file "{args.load_quest_data_from}" does not exist'
            )
            return 1
        db = QuestDatabase.from_file(args.load_quest_data_from)
    else:
        db = QuestDatabase.from_web()

    if args.dump_quest_data_to:
        db.dump_to_file(args.dump_quest_data_to)

    for quest in db.quests:
        if args.quests and quest.title not in args.quests:
            continue
        rows = []
        for skill, requirement in quest.requirements.items():
            level_data = player_levels.get(skill)
            if level_data is None:
                print(f'Unknown requirement "{skill}"')
                continue

            current_level = level_data.level
            rows.append(
                [
                    skill,
                    requirement,
                    current_level,
                    "yes" if current_level >= requirement else "no",
                ]
            )
        print(tabulate(rows, headers=["skill", "requirement", "current_level", "met"]))

    return 0


if __name__ == "__main__":
    sys.exit(main())
