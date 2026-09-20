"""Every notice must exist in both languages, and every code used must exist.

Splitting wording out of the domain makes it possible to add a Notice and never
write the Thai for it. The user would then see an English sentence, or worse a
raw code, in the middle of a Thai screen. These tests make that a test failure
instead of something a clinic discovers.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mousai.messages import EN, TH, Notice, english, thai  # noqa: E402

SOURCES = list((ROOT / "src" / "mousai").glob("*.py")) + list((ROOT / "scripts").glob("*.py"))
USED = re.compile(r'Notice\(\s*"([a-z_]+)"')


class Coverage(unittest.TestCase):
    def test_both_languages_carry_the_same_codes(self):
        self.assertEqual(sorted(TH), sorted(EN))

    def test_every_code_used_in_the_code_base_has_wording(self):
        used = set()
        for path in SOURCES:
            used |= set(USED.findall(path.read_text(encoding="utf-8")))
        self.assertTrue(used, "expected to find Notice codes in the source")
        missing = sorted(used - set(TH))
        self.assertEqual(missing, [], f"no wording for: {missing}")

    def test_thai_wording_is_actually_thai(self):
        """A copy-pasted English string in the TH table would be invisible."""
        for code, text in TH.items():
            with self.subTest(code=code):
                self.assertTrue(
                    any("฀" <= ch <= "๿" for ch in text),
                    f"{code} has no Thai characters",
                )


class Rendering(unittest.TestCase):
    def test_fills_in_values(self):
        notice = Notice("low_capacity", {"remaining": 2})
        self.assertIn("2", thai(notice))
        self.assertIn("2", english(notice))

    def test_formats_money(self):
        self.assertIn("-2.75", english(Notice("negative_balance", {"balance": -2.75})))

    def test_an_unknown_code_degrades_instead_of_raising(self):
        self.assertIn("mystery", thai(Notice("mystery", {"a": 1})))

    def test_a_missing_value_degrades_instead_of_raising(self):
        self.assertIn("low_capacity", thai(Notice("low_capacity", {})))

    def test_str_gives_english_for_logs_and_terminals(self):
        self.assertEqual(str(Notice("bad_date")), EN["bad_date"])


if __name__ == "__main__":
    unittest.main()
