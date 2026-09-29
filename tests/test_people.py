"""The people file: who may use the bot, and as what."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mousai.messages import english, thai  # noqa: E402
from mousai.people import (  # noqa: E402
    PeopleError,
    PeopleFile,
    load,
    parse,
    path_from_env,
)

MINIMAL = """
[[person]]
telegram_id = 1
name = "สมศรี"
roles = ["keeper", "operator"]
"""


def refusal(attempt):
    """The Notice a PeopleError carries, or a failure if nothing was refused."""
    try:
        attempt()
    except PeopleError as error:
        return error.notice
    raise AssertionError("expected the people file to be refused")


def refused(text: str) -> str:
    return refusal(lambda: parse(text)).code


class TheExample(unittest.TestCase):
    """The committed example must itself be a valid file."""

    def setUp(self):
        self.people = load(ROOT / "people.example.toml")

    def test_it_parses(self):
        self.assertEqual(len(self.people.by_id), 4)

    def test_roles(self):
        mon = self.people.get(111111111)
        helper = self.people.get(333333333)
        operator = self.people.get(444444444)
        self.assertTrue(mon.is_keeper and mon.may_hand_in)
        self.assertTrue(helper.may_hand_in)
        self.assertFalse(helper.is_keeper)
        self.assertTrue(operator.is_operator)
        self.assertFalse(operator.may_hand_in)

    def test_requester_defaults_to_the_name(self):
        self.assertEqual(self.people.get(111111111).requester, "สมศรี")
        self.assertEqual(self.people.get(222222222).requester, "-")

    def test_keepers_and_operators(self):
        self.assertEqual({p.telegram_id for p in self.people.keepers}, {111111111, 222222222})
        self.assertEqual([p.telegram_id for p in self.people.operators], [444444444])

    def test_a_stranger_is_nobody(self):
        self.assertIsNone(self.people.get(999))


class Refusals(unittest.TestCase):
    def test_broken_toml(self):
        self.assertEqual(refused("[[person]\ntelegram_id = 1"), "people_unreadable")

    def test_missing_fields(self):
        for field in ("telegram_id", "name", "roles"):
            text = MINIMAL.replace(
                {"telegram_id": "telegram_id = 1\n", "name": 'name = "สมศรี"\n',
                 "roles": 'roles = ["keeper", "operator"]\n'}[field], ""
            )
            with self.subTest(field=field):
                self.assertEqual(refused(text), "people_missing_field")

    def test_an_id_must_be_a_positive_number(self):
        for bad in ('"111"', "true", "-5", "0"):
            with self.subTest(bad=bad):
                self.assertEqual(
                    refused(MINIMAL.replace("telegram_id = 1", f"telegram_id = {bad}")),
                    "people_bad_id",
                )

    def test_unknown_role(self):
        text = MINIMAL.replace('"operator"]', '"operator", "admin"]')
        notice = refusal(lambda: parse(text))
        self.assertEqual(notice.code, "people_unknown_role")
        self.assertIn("admin", english(notice))

    def test_empty_roles(self):
        text = MINIMAL.replace('roles = ["keeper", "operator"]', "roles = []")
        self.assertEqual(refused(text), "people_missing_field")

    def test_the_same_id_twice(self):
        text = MINIMAL + MINIMAL.replace('"สมศรี"', '"คนอื่น"')
        notice = refusal(lambda: parse(text))
        self.assertEqual(notice.code, "people_duplicate_id")
        self.assertIn("1", english(notice))

    def test_someone_must_be_a_keeper(self):
        self.assertEqual(refused(MINIMAL.replace('"keeper", ', "")), "people_no_keeper")

    def test_someone_must_be_an_operator(self):
        self.assertEqual(refused(MINIMAL.replace(', "operator"', "")), "people_no_operator")

    def test_a_missing_file(self):
        notice = refusal(lambda: load(Path(tempfile.gettempdir()) / "no-such-people-file.toml"))
        self.assertEqual(notice.code, "people_missing")

    def test_every_refusal_reads_in_thai(self):
        for text in ("[[", MINIMAL.replace('"keeper", ', "")):
            notice = refusal(lambda: parse(text))
            self.assertNotIn(notice.code, thai(notice))


class Reloading(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "people.toml"
        self.write(MINIMAL)
        self.file = PeopleFile(self.path)

    def tearDown(self):
        self.dir.cleanup()

    def write(self, text: str, bump: int = 0) -> None:
        self.path.write_text(text, encoding="utf-8")
        # Some file systems stamp coarsely; make each edit visibly newer.
        stamp = 1_800_000_000 + bump
        os.utime(self.path, (stamp, stamp))

    def test_an_added_person_is_seen_without_a_restart(self):
        self.write(MINIMAL + '\n[[person]]\ntelegram_id = 2\nname = "ผู้ช่วย"\nroles = ["recorder"]\n', 1)
        self.assertIsNotNone(self.file.current().get(2))
        self.assertIsNone(self.file.problem)

    def test_a_broken_edit_keeps_the_last_good_list(self):
        self.write("[[person]\nbroken", 1)
        people = self.file.current()
        self.assertIsNotNone(people.get(1))
        self.assertEqual(self.file.problem.code, "people_unreadable")

    def test_fixing_the_file_clears_the_problem(self):
        self.write("[[person]\nbroken", 1)
        self.file.current()
        self.write(MINIMAL, 2)
        self.file.current()
        self.assertIsNone(self.file.problem)

    def test_the_first_read_must_succeed(self):
        self.write("broken [[", 3)
        refusal(lambda: PeopleFile(self.path))


class Location(unittest.TestCase):
    def test_defaults_beside_the_code(self):
        self.assertEqual(path_from_env({}), ROOT / "people.toml")

    def test_a_relative_setting_is_resolved_against_the_repo(self):
        self.assertEqual(path_from_env({"MOUSAI_PEOPLE_FILE": "conf/p.toml"}), ROOT / "conf" / "p.toml")


if __name__ == "__main__":
    unittest.main()
