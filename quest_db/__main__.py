import argparse
import json
import pathlib
import re
import sys
from collections import deque
from typing import Any, Dict, List, NamedTuple

import requests
from bs4 import BeautifulSoup
from tabulate import tabulate

import mwparserfromhell

from .level import LevelNameType, get_levels


class DetailsNotFoundError(Exception):
    pass


class TooManyDetailsFoundError(Exception):
    pass


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
            text = span.get_text().strip().split("\xa0")[0]
            if not text:
                continue

            self._requirements[span.find("a")["title"].lower()] = int(text)

        self.__loaded = True

    def _as_dict(self) -> Dict[str, Any]:
        return {
            "number": self.number,
            "title": self.title,
            "slug": self.slug,
            "difficulty": self.difficulty,
            "length": self.length,
            "quest_points": self.quest_points,
            "series": self.series,
        }


class QuestDatabase:
    def __init__(self, quest_data: List[Quest]) -> None:
        self._quest_dict = {q.title: q for q in quest_data}

    @property
    def quests(self):
        return self._quest_dict.values()

    def quest_exists(self, title):
        return title in self._quest_dict

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
            json.dump([q._as_dict() for q in self.quests], f, sort_keys=True, indent=4)


class Requirement:
    def __init__(self):
        self.parent = None
        self.dependencies = []

    def add_dependency(self, dependency):
        self.dependencies.append(dependency)
        dependency.parent = self

    @property
    def _dependency_repr(self):
        if not self.dependencies:
            return ""

        return ", " + ", ".join([str(d) for d in self.dependencies])

    def __str__(self):
        return self.__repr__()


class EmptyRequirement(Requirement):
    pass


class UnknownRequirement(Requirement):
    def __init__(self, text):
        super().__init__()
        self.text = text

    def __repr__(self):
        return f"UnknownRequirement({self.text})"

    @property
    def dot_repr(self):
        return f'"{self.text}"'


class QuestRequirement(Requirement):
    def __init__(self, name):
        super().__init__()
        self.name = name
        self.queried = False

    def __repr__(self):
        return f"QuestRequirement({self.name}{self._dependency_repr})"

    @property
    def dot_repr(self):
        return f'"{self.name}"'


class SkillRequirement(Requirement):
    def __init__(self, name, level):
        super().__init__()
        self.name = name
        self.level = level

    def __repr__(self):
        return f"SkillRequirement({self.level} {self.name})"

    @property
    def dot_repr(self):
        return f'"{self.level} {self.name}"'


def remove_empty_requirements(requirements):
    if not requirements or not requirements.dependencies:
        return requirements

    queue = deque()
    for dependency in requirements.dependencies:
        queue.append(dependency)

    paths = []
    while queue:
        dependency = queue.popleft()

        for dep in dependency.dependencies:
            if isinstance(dependency, EmptyRequirement):
                dep.parent = dependency.parent
                dep.parent.add_dependency(dep)
            queue.append(dep)

        if isinstance(dependency, EmptyRequirement):
            dependency.parent.dependencies.remove(dependency)
            dependency.parent = None

    return requirements


def parse_requirements(
    quest_db, quest_name, requirements: mwparserfromhell.wikicode.Wikicode
):
    skills = []
    root_requirement = QuestRequirement(quest_name)
    requirement = root_requirement
    last_req = None
    last_level = 0
    for part in str(requirements).strip().split("\n"):
        part = part[1:]
        full_len = len(part)
        part = part.lstrip("*")
        current_level = full_len - len(part)
        if current_level > last_level:
            if current_level - last_level > 1:
                print(f"WTF GROWING TOO MUCH {current_level} {last_level}")
                1 / 0

            requirement = last_req
            last_level = current_level
        else:
            while current_level < last_level:
                if requirement is root_requirement:
                    print(f"WTF CAN'T GO ANY FURTHER UP {current_level} {last_level}")
                    1 / 0

                if requirement.parent is None:
                    print(f"WTF NO PARENT {requirement}")
                    1 / 0

                requirement = requirement.parent
                last_level -= 1

        if not any(p in part for p in {"{{", "[["}):
            last_req = EmptyRequirement()
            requirement.add_dependency(last_req)
            continue

        if "Skill clickpic" in part:
            skill_parts = part.replace("{", "").replace("}", "").split("|")
            last_req = SkillRequirement(
                skill_parts[1], int(skill_parts[2].split(" ")[0])
            )
            requirement.add_dependency(last_req)
            continue

        matches = re.findall(r"\[\[([^\]]+?)\]\]", part)
        found_useful_thing = False
        for match in matches:
            if quest_db.quest_exists(match):
                last_req = QuestRequirement(match)
                found_useful_thing = True
                requirement.add_dependency(last_req)

        if not found_useful_thing:
            last_req = UnknownRequirement(
                part.lstrip("*").replace("[", "").replace("]", "")
            )
            requirement.add_dependency(last_req)

    root_requirement = remove_empty_requirements(root_requirement)

    root_requirement.queried = True
    return root_requirement


def find_quest(requirements, quest_name):
    if not requirements.dependencies and requirements.name != quest_name:
        return None

    queue = deque()
    for dependency in requirements.dependencies:
        queue.append(dependency)

    paths = []
    while queue:
        dependency = queue.popleft()
        if dependency.name == quest_name:
            return dependency

        for dep in dependency.dependencies:
            queue.append(dep)

    return None


def build_dot_repr(requirements):
    quests = []
    skills = []

    initial_repr = requirements.dot_repr
    if not requirements.dependencies:
        return initial_repr

    quests.append(initial_repr + ";")

    queue = deque()
    for dependency in requirements.dependencies:
        queue.append(dependency)

    paths = []
    while queue:
        dependency = queue.popleft()
        dot_repr = dependency.dot_repr
        if isinstance(dependency, QuestRequirement):
            quests.append(dot_repr + ";")
        elif isinstance(dependency, SkillRequirement):
            skills.append(dot_repr + ";")

        paths.append(f"{dependency.dot_repr} -> {dependency.parent.dot_repr};")
        for dep in dependency.dependencies:
            queue.append(dep)

    lines = ["digraph {", "  node[style=filled, fillcolor=darkslategray1];"]
    lines.extend(["  " + q for q in quests])
    if skills:
        lines.append("  node[style=filled, fillcolor=darkseagreen];")
        lines.extend(["  " + s for s in skills])

    lines.append("  node[style=filled, fillcolor=white];")
    lines.extend(["  " + p for p in paths])
    lines.append("}")
    return "\n".join(lines)


def get_quest_requirements(quest_db, quest_name):
    custom_agent = {"User-Agent": "quest-script", "From": "user@script"}

    # Construct the parameters of the API query
    parameters = {
        "action": "parse",
        "prop": "wikitext",
        "format": "json",
        "page": f"{quest_name}/Quick guide",
    }

    # Call the API using the custom user-agent and parameters
    result = requests.get(
        "https://oldschool.runescape.wiki/api.php",
        headers=custom_agent,
        params=parameters,
    ).json()
    p = mwparserfromhell.parse(result["parse"]["wikitext"]["*"])
    templates = p.filter_templates(matches="Quest details")
    if not templates:
        raise DetailsNotFoundError

    if len(templates) > 1:
        raise TooManyDetailsFoundError

    template = templates[0]
    requirements = parse_requirements(
        quest_db, quest_name, template.get("requirements").value
    )

    print(build_dot_repr(requirements))
    # print(find_quest(requirements, "Dream Mentor"))


def main():
    args = parse_args()

    # player_levels = get_levels(args.player)

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

    get_quest_requirements(db, args.quests[0])

    return 0

    for quest in db.quests:
        if args.quests and quest.title not in args.quests:
            continue
        rows = []
        for skill, requirement in quest.requirements.items():
            level_data = player_levels.get(skill)
            if level_data is None:
                print(f'Unknown requirement "{skill}"')
                continue

            current_level = level_data["level"]
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
