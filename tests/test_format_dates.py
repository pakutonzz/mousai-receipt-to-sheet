"""Offline tests for the date reformat.

The risk in this script is scope: a wrong range or a loose field mask would
repaint cells nobody asked it to touch. Both are pinned here, and the column
discovery is checked against every sheet of the real Workbook.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import format_dates  # noqa: E402
from test_page import BASELINE, grid_for  # noqa: E402


class ColumnDiscovery(unittest.TestCase):
    def test_finds_the_date_column_on_every_sheet_with_a_region(self):
        for name in BASELINE["sheet_order"]:
            sheet = BASELINE["sheets"][name]
            with self.subTest(sheet=name):
                found = format_dates.locate_date_column(grid_for(name))
                self.assertIsNotNone(found, f"{name} has a region in the baseline")
                _, first_row, last_row = found
                self.assertEqual(first_row, sheet["data_region"]["first_row"])
                self.assertEqual(last_row, sheet["data_region"]["last_row"])

    def test_petty_cash_dates_are_in_column_b(self):
        column, first, last = format_dates.locate_date_column(grid_for("เงินสดย่อย6"))
        self.assertEqual((column, first, last), (2, 8, 31))

    def test_emergency_dates_are_in_column_a(self):
        column, first, last = format_dates.locate_date_column(grid_for("เงินฉุกเฉิน3"))
        self.assertEqual((column, first, last), (1, 8, 33))

    def test_certificates_use_their_own_marker_and_column(self):
        column, first, last = format_dates.locate_date_column(
            grid_for("ใบรับรองแทนสดย่อย5")
        )
        self.assertEqual((column, first, last), (3, 13, 21))

    def test_a_sheet_with_no_markers_is_skipped(self):
        self.assertIsNone(format_dates.locate_date_column([["x", "y"], ["1", "2"]]))


class RequestScope(unittest.TestCase):
    def setUp(self):
        self.request = format_dates.build_format_request(42, 2, 8, 31)["repeatCell"]

    def test_touches_only_the_number_format(self):
        """A looser mask here would repaint borders on the printed form."""
        self.assertEqual(self.request["fields"], "userEnteredFormat.numberFormat")

    def test_covers_exactly_the_data_region(self):
        self.assertEqual(
            self.request["range"],
            {
                "sheetId": 42,
                "startRowIndex": 7,     # row 8, zero-indexed
                "endRowIndex": 31,      # exclusive: through row 31
                "startColumnIndex": 1,  # column B
                "endColumnIndex": 2,
            },
        )

    def test_never_reaches_the_totals_row(self):
        """เงินสดย่อย6 totals sit on row 32; endRowIndex is exclusive."""
        self.assertLess(self.request["range"]["endRowIndex"], 32)

    def test_sets_a_day_first_pattern(self):
        self.assertEqual(
            self.request["cell"]["userEnteredFormat"]["numberFormat"],
            {"type": "DATE", "pattern": "dd/mm/yyyy"},
        )


if __name__ == "__main__":
    unittest.main()
