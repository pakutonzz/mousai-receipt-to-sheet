"""Offline tests for receipt text parsing, on realistic Thai receipt layouts."""

from __future__ import annotations

import datetime as dt
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mousai.receipt import parse_amount, parse_date, parse_description, read  # noqa: E402

SEVEN_ELEVEN = """บริษัท ซีพี ออลล์ จำกัด (มหาชน)
สาขา 00123 สุขุมวิท 39
เลขประจำตัวผู้เสียภาษี 0107542000011
โทร. 021234567
ขนมปังฟาร์มเฮ้าส์          23.00
รวม                        23.00
เงินสด                     100.00
เงินทอน                     77.00
03/08/2026 14:23
"""

WITH_VAT = """ร้านกาแฟ
ลาเต้เย็น                  65.00
ส่วนลด                      5.00
ยอดสุทธิ                   65.00
ภาษีมูลค่าเพิ่ม 7%          4.25
รับเงิน                   100.00
ทอน                        35.00
วันที่ 23/7/69
"""

THAI_DIGITS_RECEIPT = """ร้านข้าวมันไก่
ข้าวมันไก่                 ๗๐.๐๐
รวมทั้งสิ้น                ๗๐.๐๐
"""


class Amounts(unittest.TestCase):
    def test_prefers_the_total_line_over_cash_tendered(self):
        """The largest number on this receipt is 100.00, which is not the total."""
        amount, why = parse_amount(SEVEN_ELEVEN)
        self.assertEqual(amount, 23.00)
        self.assertIn("รวม", why)

    def test_ignores_change_and_vat_lines(self):
        amount, _ = parse_amount(WITH_VAT)
        self.assertEqual(amount, 65.00)

    def test_thai_digits(self):
        amount, _ = parse_amount(THAI_DIGITS_RECEIPT)
        self.assertEqual(amount, 70.00)

    def test_thousands_separator(self):
        amount, _ = parse_amount("รวมทั้งสิ้น 2,061.00")
        self.assertEqual(amount, 2061.00)

    def test_amount_on_the_following_line(self):
        amount, why = parse_amount("ยอดสุทธิ\n1,558.00\n")
        self.assertEqual(amount, 1558.00)
        self.assertIn("after", why)

    def test_leaves_it_blank_when_no_total_line_is_found(self):
        """Across 24 real receipts, guessing at the largest number was never
        once right. A blank field is safer than a plausible wrong one in a
        preview whose whole job is to be checked."""
        amount, why = parse_amount("ก๋วยเตี๋ยว 60.00\nน้ำ 15.00\n")
        self.assertIsNone(amount)
        self.assertIn("no amount", why)

    def test_ignores_tax_ids_and_phone_numbers(self):
        amount, _ = parse_amount(
            "เลขประจำตัวผู้เสียภาษี 0107542000011\nโทร. 021234567\nรวม 48.00"
        )
        self.assertEqual(amount, 48.00)

    def test_nothing_to_find(self):
        amount, why = parse_amount("ขอบคุณที่ใช้บริการ")
        self.assertIsNone(amount)
        self.assertIn("no amount", why)


class Dates(unittest.TestCase):
    TODAY = dt.date(2026, 8, 5)

    def test_day_first_slashes(self):
        found, _ = parse_date(SEVEN_ELEVEN, today=self.TODAY)
        self.assertEqual(found, dt.date(2026, 8, 3))

    def test_two_digit_buddhist_year(self):
        """23/7/69 is 23 July 2026, not 2069."""
        found, _ = parse_date(WITH_VAT, today=self.TODAY)
        self.assertEqual(found, dt.date(2026, 7, 23))

    def test_four_digit_buddhist_year(self):
        found, _ = parse_date("วันที่ 3/8/2569", today=self.TODAY)
        self.assertEqual(found, dt.date(2026, 8, 3))

    def test_thai_month_name(self):
        found, _ = parse_date("3 ส.ค. 69", today=self.TODAY)
        self.assertEqual(found, dt.date(2026, 8, 3))

    def test_iso(self):
        found, _ = parse_date("2026-08-03", today=self.TODAY)
        self.assertEqual(found, dt.date(2026, 8, 3))

    def test_ignores_dates_far_from_today(self):
        """Warranty and printed-footer years should not become the Entry date."""
        found, _ = parse_date("พิมพ์เมื่อ 01/01/2019", today=self.TODAY)
        self.assertIsNone(found)

    def test_rejects_impossible_dates(self):
        found, _ = parse_date("32/13/2026", today=self.TODAY)
        self.assertIsNone(found)


class Descriptions(unittest.TestCase):
    def test_takes_the_shop_name(self):
        found, _ = parse_description(SEVEN_ELEVEN)
        self.assertEqual(found, "บริษัท ซีพี ออลล์ จำกัด (มหาชน)")

    def test_skips_number_heavy_lines(self):
        found, _ = parse_description("0107542000011\n021234567\nร้านกาแฟ\n")
        self.assertEqual(found, "ร้านกาแฟ")


class WholeReading(unittest.TestCase):
    def test_reads_a_seven_eleven_receipt(self):
        reading = read(SEVEN_ELEVEN, today=dt.date(2026, 8, 5))
        self.assertEqual(reading.amount, 23.00)
        self.assertEqual(reading.date, dt.date(2026, 8, 3))
        self.assertIn("ซีพี ออลล์", reading.description)
        self.assertFalse(reading.empty)
        self.assertEqual(len(reading.notes), 3)

    def test_unreadable_text_yields_an_empty_reading(self):
        reading = read("~~~~~~")
        self.assertTrue(reading.empty)


if __name__ == "__main__":
    unittest.main()
