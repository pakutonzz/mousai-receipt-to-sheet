"""Offline tests for the domain logic, against the real Workbook's baseline.

Stdlib unittest so these run with nothing installed:

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mousai import EMERGENCY, PETTY_CASH, Formula, Page  # noqa: E402
from mousai.page import (  # noqa: E402
    NoOpeningRow,
    RegionFull,
    column_index,
    to_serial,
)

BASELINE = json.loads(
    (ROOT / "tests" / "fixtures" / "baseline.json").read_text(encoding="utf-8")
)


def grid_for(sheet_name: str) -> list[list]:
    """Rebuild the sheet as the Sheets API would hand it back."""
    cells = BASELINE["sheets"][sheet_name]["cells"]
    height = width = 0
    parsed = {}
    for ref, cell in cells.items():
        letters = "".join(c for c in ref if c.isalpha())
        row = int("".join(c for c in ref if c.isdigit()))
        col = column_index(letters)
        parsed[(row, col)] = cell["v"]
        height, width = max(height, row), max(width, col)
    grid = [["" for _ in range(width)] for _ in range(height)]
    for (row, col), value in parsed.items():
        grid[row - 1][col - 1] = value
    return grid


def occupy(grid: list[list], row: int, template, description: str, balance: float):
    """Fill a row in-place, so capacity edges can be tested."""
    while len(grid) < row:
        grid.append(["" for _ in range(len(grid[0]))])
    grid[row - 1][column_index(template.sequence) - 1] = 1
    grid[row - 1][column_index(template.description) - 1] = description
    grid[row - 1][column_index(template.disbursed) - 1] = 1
    grid[row - 1][column_index(template.balance) - 1] = balance


class RegionDiscovery(unittest.TestCase):
    def test_matches_the_baseline_on_every_detail_page(self):
        pages = {
            **{n: PETTY_CASH for n in BASELINE["sheet_order"] if n.startswith("เงินสดย่อย")},
            **{n: EMERGENCY for n in BASELINE["sheet_order"] if n.startswith("เงินฉุกเฉิน")},
        }
        self.assertEqual(len(pages), 11)
        for name, template in pages.items():
            with self.subTest(page=name):
                page = Page(name, template, grid_for(name))
                expected = BASELINE["sheets"][name]["data_region"]
                self.assertEqual(page.first_row, expected["first_row"])
                self.assertEqual(page.last_row, expected["last_row"])

    def test_regions_differ_within_one_fund(self):
        """The reason the region is discovered rather than configured."""
        spans = {
            name: Page(name, PETTY_CASH, grid_for(name)).last_row
            for name in BASELINE["sheet_order"]
            if name.startswith("เงินสดย่อย")
        }
        self.assertGreater(len(set(spans.values())), 1, spans)


class ActivePages(unittest.TestCase):
    def test_petty_cash_6(self):
        page = Page("เงินสดย่อย6", PETTY_CASH, grid_for("เงินสดย่อย6"))
        self.assertEqual(page.free_row, 21)
        self.assertEqual(page.rows_remaining, 11)
        self.assertEqual(page.effective_date, dt.date(2026, 7, 28))
        self.assertEqual(page.last_entry.balance, 20.25)

    def test_emergency_3(self):
        page = Page("เงินฉุกเฉิน3", EMERGENCY, grid_for("เงินฉุกเฉิน3"))
        self.assertEqual(page.free_row, 29)
        self.assertEqual(page.rows_remaining, 5)
        self.assertEqual(page.last_entry.balance, 1603.25)


class AcceptanceTest(unittest.TestCase):
    """23 baht, ค่าขนมปังรับรองลูกค้า, เงินสดย่อย."""

    def setUp(self):
        self.page = Page("เงินสดย่อย6", PETTY_CASH, grid_for("เงินสดย่อย6"))
        self.placed = self.page.place(
            on=dt.date(2026, 8, 3),
            description="ค่าขนมปังรับรองลูกค้า",
            amount=23,
            requester="-",
        )

    def test_lands_on_the_first_free_row(self):
        self.assertEqual(self.placed.row, 21)

    def test_writes_the_date_and_restarts_the_sequence(self):
        self.assertTrue(self.placed.write_date)
        self.assertEqual(self.placed.sequence, 1)

    def test_balance_chains_off_the_row_above(self):
        self.assertEqual(self.placed.balance, -2.75)
        self.assertEqual(self.placed.cells["G21"], Formula("=G20-F21"))

    def test_writes_only_into_the_free_row(self):
        rows = {int("".join(c for c in ref if c.isdigit())) for ref in self.placed.cells}
        self.assertEqual(rows, {21})

    def test_never_touches_totals_or_signatures(self):
        for ref in self.placed.cells:
            row = int("".join(c for c in ref if c.isdigit()))
            self.assertLess(row, self.page.totals_row)

    def test_cell_values(self):
        self.assertEqual(
            self.placed.cells,
            {
                "B21": to_serial(dt.date(2026, 8, 3)),
                "C21": 1,
                "D21": "ค่าขนมปังรับรองลูกค้า",
                "E21": "-",
                "F21": 23.0,
                "G21": Formula("=G20-F21"),
                "H21": "-",
            },
        )

    def test_warns_about_the_negative_balance_without_blocking(self):
        self.assertTrue(any("negative" in w for w in self.placed.warnings))


class DateAndSequence(unittest.TestCase):
    def setUp(self):
        self.page = Page("เงินสดย่อย6", PETTY_CASH, grid_for("เงินสดย่อย6"))

    def test_same_day_leaves_the_date_blank_and_continues_the_sequence(self):
        placed = self.page.place(
            on=dt.date(2026, 7, 28), description="ค่ากาแฟคุณหมอ", amount=10
        )
        self.assertFalse(placed.write_date)
        self.assertNotIn("B21", placed.cells)
        self.assertEqual(placed.sequence, 3)

    def test_new_day_writes_the_date_and_restarts(self):
        placed = self.page.place(
            on=dt.date(2026, 7, 29), description="ค่ากาแฟคุณหมอ", amount=10
        )
        self.assertTrue(placed.write_date)
        self.assertEqual(placed.sequence, 1)

    def test_backdating_warns_but_still_appends(self):
        placed = self.page.place(
            on=dt.date(2026, 7, 1), description="เบิกย้อนหลัง", amount=10
        )
        self.assertEqual(placed.row, 21)
        self.assertTrue(any("earlier than" in w for w in placed.warnings))

    def test_note_goes_in_the_column_labelled_approver(self):
        placed = self.page.place(
            on=dt.date(2026, 8, 3), description="x", amount=1, note="รอเบิกเพิ่ม"
        )
        self.assertEqual(placed.cells["I21"], "รอเบิกเพิ่ม")


class EmergencyTemplate(unittest.TestCase):
    def test_uses_its_own_columns(self):
        page = Page("เงินฉุกเฉิน3", EMERGENCY, grid_for("เงินฉุกเฉิน3"))
        placed = page.place(
            on=dt.date(2026, 9, 1), description="ค่าขยะติดเชื้อ", amount=780
        )
        self.assertEqual(placed.row, 29)
        self.assertEqual(placed.balance, 823.25)
        self.assertEqual(
            placed.cells,
            {
                "A29": to_serial(dt.date(2026, 9, 1)),
                "B29": 1,
                "C29": "ค่าขยะติดเชื้อ",
                "D29": "-",
                "E29": 780.0,
                "F29": Formula("=F28-E29"),
                "G29": "-",
            },
        )


class Refusals(unittest.TestCase):
    def test_a_full_page_refuses(self):
        page = Page("เงินสดย่อย5", PETTY_CASH, grid_for("เงินสดย่อย5"))
        self.assertEqual(page.rows_remaining, 0)
        with self.assertRaises(RegionFull):
            page.place(on=dt.date(2026, 8, 24), description="x", amount=1)

    def test_a_page_with_no_opening_row_refuses(self):
        grid = grid_for("เงินสดย่อย6")
        for row in range(8, 32):  # clear the data region, keep head and totals
            for col in range(1, len(grid[0]) + 1):
                grid[row - 1][col - 1] = ""
        page = Page("blank", PETTY_CASH, grid)
        self.assertIsNone(page.free_row)
        with self.assertRaises(NoOpeningRow):
            page.place(on=dt.date(2026, 9, 1), description="x", amount=1)


class CapacityWarning(unittest.TestCase):
    """issues/01: warn below three rows left."""

    def test_quiet_while_there_is_headroom(self):
        page = Page("เงินสดย่อย6", PETTY_CASH, grid_for("เงินสดย่อย6"))
        placed = page.place(on=dt.date(2026, 8, 3), description="x", amount=1)
        self.assertEqual(placed.rows_remaining, 10)
        self.assertFalse(any("row(s) left" in w for w in placed.warnings))

    def test_warns_when_the_page_is_nearly_full(self):
        grid = grid_for("เงินฉุกเฉิน3")
        occupy(grid, 29, EMERGENCY, "filler", 1500.0)
        occupy(grid, 30, EMERGENCY, "filler", 1400.0)
        page = Page("เงินฉุกเฉิน3", EMERGENCY, grid)
        placed = page.place(on=dt.date(2026, 9, 1), description="x", amount=1)
        self.assertEqual(placed.row, 31)
        self.assertEqual(placed.rows_remaining, 2)
        self.assertTrue(any("row(s) left" in w for w in placed.warnings))


if __name__ == "__main__":
    unittest.main()
