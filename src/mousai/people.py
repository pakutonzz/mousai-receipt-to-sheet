"""Who may use the bot, and as what: a file of people, edited by hand.

Each person is known by their Telegram user ID and has one or more roles:

- `keeper` may confirm Transactions into the Workbook, and hands in their own.
- `recorder` hands Transactions in; they wait in the Queue for a Keeper.
- `operator` receives access requests and system failures, not book matters.

Each person also has a default Requester, the name the bot puts in ผู้เบิก
unless they choose another. It need not be in the Workbook's ผู้เบิก column
yet: the column only learns a name once it is used.

The file is re-read when it changes, so adding someone needs no restart. An
edit that breaks it is refused and the last good list stays in force, so a
typo cannot lock the clinic out.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .messages import Notice
from .sheets import beside_the_code

ROLES = ("keeper", "recorder", "operator")

DEFAULT_PATH = "people.toml"


class PeopleError(Exception):
    def __init__(self, notice: Notice):
        self.notice = notice
        super().__init__(notice.code)


@dataclass(frozen=True)
class Person:
    telegram_id: int
    name: str
    requester: str
    roles: frozenset[str]

    @property
    def is_keeper(self) -> bool:
        return "keeper" in self.roles

    @property
    def may_hand_in(self) -> bool:
        """Keepers are Recorders too; an operator alone is not."""
        return self.is_keeper or "recorder" in self.roles

    @property
    def is_operator(self) -> bool:
        return "operator" in self.roles


@dataclass(frozen=True)
class People:
    by_id: dict[int, Person]

    def get(self, telegram_id: int) -> Person | None:
        return self.by_id.get(telegram_id)

    @property
    def keepers(self) -> list[Person]:
        return [p for p in self.by_id.values() if p.is_keeper]

    @property
    def operators(self) -> list[Person]:
        return [p for p in self.by_id.values() if p.is_operator]


def parse(text: str) -> People:
    """Read the people file's text, refusing anything ambiguous."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise PeopleError(Notice("people_unreadable", {"detail": str(error)})) from error

    entries = data.get("person", [])
    if not isinstance(entries, list):
        raise PeopleError(Notice("people_unreadable", {"detail": "[[person]] blocks expected"}))

    by_id: dict[int, Person] = {}
    first_seen: dict[int, int] = {}
    for number, entry in enumerate(entries, start=1):
        label = f"{number}" + (f" ({entry['name']})" if isinstance(entry.get("name"), str) else "")
        for field in ("telegram_id", "name", "roles"):
            if field not in entry:
                raise PeopleError(Notice("people_missing_field", {"entry": label, "field": field}))
        telegram_id = entry["telegram_id"]
        # bool is an int in Python; true is not anybody's Telegram ID.
        if not isinstance(telegram_id, int) or isinstance(telegram_id, bool) or telegram_id <= 0:
            raise PeopleError(Notice("people_bad_id", {"entry": label}))
        roles = entry["roles"]
        if not isinstance(roles, list) or not roles:
            raise PeopleError(Notice("people_missing_field", {"entry": label, "field": "roles"}))
        for role in roles:
            if role not in ROLES:
                raise PeopleError(
                    Notice("people_unknown_role", {"entry": label, "role": role})
                )
        if telegram_id in by_id:
            raise PeopleError(
                Notice(
                    "people_duplicate_id",
                    {"id": telegram_id, "first": first_seen[telegram_id], "second": number},
                )
            )
        name = str(entry["name"]).strip()
        by_id[telegram_id] = Person(
            telegram_id=telegram_id,
            name=name,
            requester=str(entry.get("requester") or name).strip(),
            roles=frozenset(roles),
        )
        first_seen[telegram_id] = number

    people = People(by_id)
    if not people.keepers:
        raise PeopleError(Notice("people_no_keeper"))
    if not people.operators:
        raise PeopleError(Notice("people_no_operator"))
    return people


def path_from_env(env: dict[str, str]) -> Path:
    """MOUSAI_PEOPLE_FILE, resolved against the repo like the other paths in .env."""
    return beside_the_code(env.get("MOUSAI_PEOPLE_FILE") or DEFAULT_PATH)


def load(path: Path) -> People:
    if not path.is_file():
        raise PeopleError(Notice("people_missing", {"path": str(path)}))
    return parse(path.read_text(encoding="utf-8"))


class PeopleFile:
    """The people file, re-read whenever it changes on disk.

    The first read must succeed. After that, a change that does not parse is
    recorded in `problem` and the last good list keeps working, until the file
    is fixed.
    """

    def __init__(self, path: Path):
        self.path = path
        self._stamp = self._stat()
        self._people = load(path)
        self.problem: Notice | None = None

    def _stat(self) -> int | None:
        try:
            return os.stat(self.path).st_mtime_ns
        except OSError:
            return None

    def current(self) -> People:
        stamp = self._stat()
        if stamp != self._stamp:
            self._stamp = stamp
            try:
                self._people = load(self.path)
                self.problem = None
            except PeopleError as error:
                self.problem = error.notice
        return self._people
