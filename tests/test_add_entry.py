"""Offline tests for the end-to-end runner.

The runner is mostly glue, but two things in it can genuinely be wrong: how a
date string is read, and whether anything can reach the Workbook without a human
agreeing to it. Both are covered here against the same fake used in
test_sheets.py.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import add_entry  # noqa: E402
from test_sheets import FakeService  # noqa: E402
from mousai.sheets import Workbook  # noqa: E402
from test_page import grid_for  # noqa: E402

PAGE = "เงินสดย่อย6"


class FakeSheets:
    def __init__(self, service):
        self._service = service

    def workbooks(self, folder_id=None):
        return []

    def open(self, spreadsheet_id):
        return Workbook(self._service, spreadsheet_id)


def entry_writes(service) -> list[dict]:
    """Only the batches that write Entry cells.

    A successful run also writes the config tab, so counting raw batches would
    conflate remembering the Page with recording the Entry.
    """
    return [
        batch
        for batch in service.batches
        if any("updateCells" in request for request in batch["requests"])
    ]


def run(args: list[str], answer: str | None = None):
    """Run the CLI against a fake Workbook; returns (exit code, service, output)."""
    service = FakeService({PAGE: grid_for(PAGE)}, {PAGE: 42})
    buffer = io.StringIO()
    with mock.patch.object(add_entry.Sheets, "from_env", staticmethod(lambda *a, **k: FakeSheets(service))):
        with mock.patch("builtins.input", lambda *a: answer or ""):
            with redirect_stdout(buffer):
                code = add_entry.main(args)
    return code, service, buffer.getvalue()


class DateParsing(unittest.TestCase):
    def test_slashes_are_day_first(self):
        """3/8/2026 is 3 August. Reading it as 8 March would be silently wrong."""
        self.assertEqual(add_entry.parse_date("3/8/2026"), dt.date(2026, 8, 3))

    def test_two_digit_year(self):
        self.assertEqual(add_entry.parse_date("3/8/26"), dt.date(2026, 8, 3))

    def test_iso_also_accepted(self):
        self.assertEqual(add_entry.parse_date("2026-08-03"), dt.date(2026, 8, 3))

    def test_unambiguous_day_still_day_first(self):
        self.assertEqual(add_entry.parse_date("23/7/2026"), dt.date(2026, 7, 23))

    def test_rubbish_is_rejected(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            add_entry.parse_date("next tuesday")


class Confirmation(unittest.TestCase):
    ARGS = [
        "--amount", "23",
        "--description", "ค่าขนมปังรับรองลูกค้า",
        "--date", "3/8/2026",
        "--page", PAGE,
        "--workbook", "fake-id",
    ]

    def test_declining_writes_nothing(self):
        code, service, output = run(self.ARGS, answer="n")
        self.assertEqual(code, 1)
        self.assertEqual(service.batches, [])
        self.assertIn("cancelled", output)

    def test_empty_answer_is_a_no(self):
        code, service, _ = run(self.ARGS, answer="")
        self.assertEqual(code, 1)
        self.assertEqual(service.batches, [])

    def test_dry_run_writes_nothing_and_never_asks(self):
        code, service, output = run(self.ARGS + ["--dry-run"])
        self.assertEqual(code, 0)
        self.assertEqual(service.batches, [])
        self.assertIn("dry run", output)

    def test_accepting_writes_the_entry(self):
        code, service, output = run(self.ARGS, answer="y")
        self.assertEqual(code, 0)
        self.assertEqual(len(entry_writes(service)), 1)
        self.assertIn(f"written to {PAGE}!21", output)


class AcceptanceRun(unittest.TestCase):
    """The agreed acceptance case, driven through the real entry point."""

    def test_23_baht_lands_correctly(self):
        code, service, output = run(
            [
                "--amount", "23",
                "--description", "ค่าขนมปังรับรองลูกค้า",
                "--date", "3/8/2026",
                "--page", PAGE,
                "--workbook", "fake-id",
                "--yes",
            ]
        )
        self.assertEqual(code, 0)

        requests = entry_writes(service)[0]["requests"]
        written = {
            (r["updateCells"]["start"]["rowIndex"], r["updateCells"]["start"]["columnIndex"]):
            r["updateCells"]["rows"][0]["values"][0]["userEnteredValue"]
            for r in requests
        }
        # row 21 -> index 20; B..H -> 1..7
        self.assertEqual(sorted(written), [(20, c) for c in range(1, 8)])
        self.assertEqual(written[(20, 1)], {"numberValue": 46237.0})   # B21 date
        self.assertEqual(written[(20, 2)], {"numberValue": 1.0})       # C21 sequence
        self.assertEqual(
            written[(20, 3)], {"stringValue": "ค่าขนมปังรับรองลูกค้า"}  # D21
        )
        self.assertEqual(written[(20, 5)], {"numberValue": 23.0})      # F21 amount
        self.assertEqual(written[(20, 6)], {"formulaValue": "=G20-F21"})  # G21

    def test_preview_shows_the_negative_balance_warning(self):
        _, _, output = run(
            [
                "--amount", "23",
                "--description", "x",
                "--date", "3/8/2026",
                "--page", PAGE,
                "--workbook", "fake-id",
                "--dry-run",
            ]
        )
        self.assertIn("-2.75", output)
        self.assertIn("negative", output)
        self.assertIn("10 row(s) left", output)


if __name__ == "__main__":
    unittest.main()
