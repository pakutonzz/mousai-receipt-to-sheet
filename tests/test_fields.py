"""Answers to one direct question: an amount, a date, a Note."""

from __future__ import annotations

import datetime as dt
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mousai.bot import fields  # noqa: E402

TODAY = dt.date(2026, 1, 10)


class Amounts(unittest.TestCase):
    def test_what_people_type(self):
        for text, value in (("299", 299.0), ("1,250.50", 1250.5), ("฿45", 45.0), ("45 บาท", 45.0)):
            with self.subTest(text=text):
                self.assertEqual(fields.amount(text), value)

    def test_nothing_and_nonsense(self):
        for text in ("", "0", "-5", "สี่สิบ", "12/8"):
            with self.subTest(text=text):
                self.assertIsNone(fields.amount(text))


class Days(unittest.TestCase):
    def test_relative(self):
        self.assertEqual(fields.day("วันนี้", TODAY), TODAY)
        self.assertEqual(fields.day("เมื่อวาน", TODAY), dt.date(2026, 1, 9))
        self.assertEqual(fields.day("เมื่อวานซืน", TODAY), dt.date(2026, 1, 8))

    def test_day_first_with_any_year(self):
        for text in ("5/1/2026", "5/1/69", "5-1-2569", "5.1.26", "2026-01-05"):
            with self.subTest(text=text):
                self.assertEqual(fields.day(text, TODAY), dt.date(2026, 1, 5))

    def test_no_year_is_the_most_recent_one(self):
        """20/12 typed in January is last December."""
        self.assertEqual(fields.day("20/12", TODAY), dt.date(2025, 12, 20))
        self.assertEqual(fields.day("9/1", TODAY), dt.date(2026, 1, 9))

    def test_thai_month_names(self):
        self.assertEqual(fields.day("3 ม.ค.", TODAY), dt.date(2026, 1, 3))
        self.assertEqual(fields.day("25 ธันวาคม", TODAY), dt.date(2025, 12, 25))
        self.assertEqual(fields.day("3 สิงหาคม 2568", TODAY), dt.date(2025, 8, 3))

    def test_impossible_dates(self):
        for text in ("31/2", "0/1", "พรุ่งนี้มั้ง", "1/13"):
            with self.subTest(text=text):
                self.assertIsNone(fields.day(text, TODAY))

    def test_finding_one_in_a_sentence(self):
        on, (start, end) = fields.find_day("ค่าน้ำมัน 500 วันที่ 3 ม.ค.", TODAY)
        self.assertEqual(on, dt.date(2026, 1, 3))
        self.assertEqual("ค่าน้ำมัน 500 วันที่ 3 ม.ค."[start:end], "3 ม.ค.")
        self.assertIsNone(fields.find_day("ค่ากาแฟ 45.50", TODAY))


class Text(unittest.TestCase):
    def test_description_is_trimmed_and_bounded(self):
        self.assertEqual(fields.description("  ค่าน้ำ   ดื่ม "), "ค่าน้ำ ดื่ม")
        self.assertIsNone(fields.description("   "))
        self.assertIsNone(fields.description("ก" * (fields.MAX_DESCRIPTION + 1)))

    def test_a_dash_clears(self):
        self.assertEqual(fields.note("-"), "")
        self.assertEqual(fields.requester("-"), "-")
        self.assertEqual(fields.requester(" "), "-")


if __name__ == "__main__":
    unittest.main()
