"""Offline tests for the Sheets adapter.

No network and no credentials: the request building is a pure function, and the
parts that talk to the API are exercised against a fake that records what was
sent. Run with the rest:

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import datetime as dt
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from mousai import PETTY_CASH, Formula, Page  # noqa: E402
from mousai import EMERGENCY  # noqa: E402
from mousai.sheets import (  # noqa: E402
    CONFIG_SHEET,
    Sheets,
    WorkbookRef,
    RowTaken,
    Workbook,
    build_update_requests,
    cell_value,
    quote,
    split_ref,
)
from mousai.page import column_index  # noqa: E402
from test_page import BASELINE, grid_for  # noqa: E402


class _Execute:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class FakeService:
    """Just enough of the googleapiclient fluent interface."""

    def __init__(self, grids: dict[str, list[list]], ids: dict[str, int]):
        self.grids = grids
        self.ids = ids
        self.batches: list[dict] = []
        self.value_writes: list[tuple[str, list]] = []

    # service.spreadsheets() -> self, and it also serves .values()
    def spreadsheets(self):
        return self

    def values(self):
        return self

    def get(self, spreadsheetId=None, fields=None, range=None, **kwargs):
        if range is None:
            return _Execute(
                {
                    "properties": {"title": "fake workbook"},
                    "sheets": [
                        {"properties": {"title": name, "sheetId": sheet_id}}
                        for name, sheet_id in self.ids.items()
                    ],
                }
            )
        name = range.split("!")[0].strip("'").replace("''", "'")
        return _Execute({"values": self.grids.get(name, [])})

    def batchGet(self, spreadsheetId=None, ranges=None, **kwargs):
        blocks = []
        for r in ranges or []:
            name = r.split("!")[0].strip("'").replace("''", "'")
            blocks.append({"values": self.grids.get(name, [])})
        return _Execute({"valueRanges": blocks})

    def update(self, spreadsheetId=None, range=None, valueInputOption=None, body=None):
        self.value_writes.append((range, body["values"]))
        return _Execute({})

    def batchUpdate(self, spreadsheetId=None, body=None):
        self.batches.append(body)
        for request in body.get("requests", []):
            if "addSheet" in request:
                title = request["addSheet"]["properties"]["title"]
                self.ids[title] = 999
                self.grids.setdefault(title, [])
        return _Execute({})


def workbook_with(page_name: str = "เงินสดย่อย6") -> tuple[Workbook, FakeService]:
    service = FakeService({page_name: grid_for(page_name)}, {page_name: 42})
    return Workbook(service, "fake-id"), service


class CellTyping(unittest.TestCase):
    def test_formula_type_becomes_a_formula(self):
        self.assertEqual(
            cell_value(Formula("=G20-F21")), {"formulaValue": "=G20-F21"}
        )

    def test_a_description_that_looks_like_a_formula_stays_text(self):
        """The guarantee in ADR 0002: type decides, never the leading character."""
        for hostile in ("=SUM(A:A)", "+66 61 894 1881", "-", "@import"):
            with self.subTest(text=hostile):
                self.assertEqual(cell_value(hostile), {"stringValue": hostile})

    def test_numbers_and_dates(self):
        self.assertEqual(cell_value(23), {"numberValue": 23.0})
        self.assertEqual(cell_value(46237), {"numberValue": 46237.0})
        self.assertEqual(cell_value(2.5), {"numberValue": 2.5})

    def test_bool_is_not_mistaken_for_a_number(self):
        self.assertEqual(cell_value(True), {"boolValue": True})


class RequestBuilding(unittest.TestCase):
    def setUp(self):
        page = Page("เงินสดย่อย6", PETTY_CASH, grid_for("เงินสดย่อย6"))
        self.placement = page.place(
            on=dt.date(2026, 8, 3), description="ค่าขนมปังรับรองลูกค้า", amount=23
        )
        self.requests = build_update_requests(42, self.placement.cells)

    def test_one_request_per_cell(self):
        self.assertEqual(len(self.requests), len(self.placement.cells))

    def test_every_write_is_restricted_to_values(self):
        """fields=userEnteredValue is what stops a write touching formatting."""
        for request in self.requests:
            self.assertEqual(request["updateCells"]["fields"], "userEnteredValue")

    def test_targets_the_right_zero_indexed_cells(self):
        starts = {
            (r["updateCells"]["start"]["rowIndex"], r["updateCells"]["start"]["columnIndex"])
            for r in self.requests
        }
        # row 21 -> index 20; columns B..H -> 1..7
        self.assertEqual(starts, {(20, c) for c in range(1, 8)})

    def test_carries_the_sheet_id(self):
        for request in self.requests:
            self.assertEqual(request["updateCells"]["start"]["sheetId"], 42)

    def test_split_ref(self):
        self.assertEqual(split_ref("D21"), (21, 4))
        self.assertEqual(split_ref("AA7"), (7, 27))


class Quoting(unittest.TestCase):
    def test_names_with_spaces_and_parentheses(self):
        self.assertEqual(quote("เงินสดย่อย3 (2)"), "'เงินสดย่อย3 (2)'")

    def test_embedded_apostrophe(self):
        self.assertEqual(quote("a'b"), "'a''b'")


class FakeDrive:
    def __init__(self, files):
        self._files = files

    def files(self):
        return self

    def list(self, **kwargs):
        return _Execute({"files": self._files})


class Picker(unittest.TestCase):
    FILES = [
        {"id": "scratch", "name": "TEST scratch - do not use", "modifiedTime": "2026-09-21T10:00:00Z"},
        {"id": "august", "name": "เบิกจ่ายเงินสด สิงหาคม26", "modifiedTime": "2026-09-01T10:00:00Z"},
    ]

    def test_newest_first(self):
        sheets = Sheets(None, FakeDrive(self.FILES), folder_id="folder")
        self.assertEqual([w.id for w in sheets.workbooks()], ["scratch", "august"])

    def test_the_scratch_workbook_is_never_offered(self):
        """Otherwise a newest-wins default files real Entries into the test copy."""
        sheets = Sheets(
            None, FakeDrive(self.FILES), folder_id="folder",
            exclude_ids=frozenset({"scratch"}),
        )
        found = sheets.workbooks()
        self.assertEqual([w.id for w in found], ["august"])
        self.assertIsInstance(found[0], WorkbookRef)


class Appending(unittest.TestCase):
    def test_writes_when_the_row_is_still_free(self):
        workbook, service = workbook_with()
        page = workbook.page("เงินสดย่อย6", PETTY_CASH)
        placement = page.place(on=dt.date(2026, 8, 3), description="x", amount=23)

        workbook.append(page, placement)

        self.assertEqual(len(service.batches), 1)
        requests = service.batches[0]["requests"]
        self.assertEqual(len(requests), len(placement.cells))
        self.assertTrue(
            all(r["updateCells"]["start"]["rowIndex"] == 20 for r in requests)
        )

    def test_refuses_when_someone_took_the_row_first(self):
        workbook, service = workbook_with()
        page = workbook.page("เงินสดย่อย6", PETTY_CASH)
        placement = page.place(on=dt.date(2026, 8, 3), description="x", amount=23)

        # someone types into row 21 between the preview and the Confirm
        grid = service.grids["เงินสดย่อย6"]
        grid[20][3] = "ค่ากาแฟ typed by a human"

        with self.assertRaises(RowTaken):
            workbook.append(page, placement)
        self.assertEqual(service.batches, [], "nothing should have been written")


class ConfigTab(unittest.TestCase):
    def test_absent_config_means_no_active_page(self):
        workbook, _ = workbook_with()
        self.assertIsNone(workbook.active_page("เงินสดย่อย"))

    def test_first_remember_creates_the_tab_hidden(self):
        workbook, service = workbook_with()
        workbook.remember_page("เงินสดย่อย", "เงินสดย่อย6")

        added = [r for b in service.batches for r in b["requests"] if "addSheet" in r]
        self.assertEqual(len(added), 1)
        properties = added[0]["addSheet"]["properties"]
        self.assertEqual(properties["title"], CONFIG_SHEET)
        self.assertTrue(properties["hidden"], "config tab must never print")

        self.assertEqual(
            service.value_writes[-1][1],
            [["fund", "active_page"], ["เงินสดย่อย", "เงินสดย่อย6"]],
        )

    def test_remembering_again_replaces_rather_than_appends(self):
        workbook, service = workbook_with()
        service.ids[CONFIG_SHEET] = 7
        service.grids[CONFIG_SHEET] = [
            ["fund", "active_page"],
            ["เงินสดย่อย", "เงินสดย่อย5"],
            ["เงินฉุกเฉิน", "เงินฉุกเฉิน3"],
        ]
        workbook._meta = None

        workbook.remember_page("เงินสดย่อย", "เงินสดย่อย6")

        self.assertEqual(
            service.value_writes[-1][1],
            [
                ["fund", "active_page"],
                ["เงินสดย่อย", "เงินสดย่อย6"],
                ["เงินฉุกเฉิน", "เงินฉุกเฉิน3"],
            ],
        )

    def test_reads_back_the_active_page(self):
        workbook, service = workbook_with()
        service.ids[CONFIG_SHEET] = 7
        service.grids[CONFIG_SHEET] = [
            ["fund", "active_page"],
            ["เงินฉุกเฉิน", "เงินฉุกเฉิน3"],
        ]
        self.assertEqual(workbook.active_page("เงินฉุกเฉิน"), "เงินฉุกเฉิน3")
        self.assertIsNone(workbook.active_page("เงินสดย่อย"))


if __name__ == "__main__":
    unittest.main()


class WritablePages(unittest.TestCase):
    def build(self):
        names = [
            "แจกแจง", "ย่อย", "ฉฉ", "PT",
            "เงินสดย่อย5", "เงินสดย่อย6", "เงินฉุกเฉิน3",
            "ใบรับรองแทนสดย่อย5", CONFIG_SHEET,
        ]
        service = FakeService(
            {n: grid_for(n) for n in names if n in BASELINE["sheets"]},
            {n: i for i, n in enumerate(names)},
        )
        return Workbook(service, "fake-id"), service

    def test_offers_pages_from_both_funds(self):
        workbook, _ = self.build()
        names = [n for n, _ in workbook.writable_pages()]
        self.assertEqual(names, ["เงินสดย่อย5", "เงินสดย่อย6", "เงินฉุกเฉิน3"])

    def test_skips_ledgers_certificates_and_the_config_tab(self):
        workbook, _ = self.build()
        names = [n for n, _ in workbook.writable_pages()]
        for excluded in ("ย่อย", "ฉฉ", "PT", "แจกแจง", "ใบรับรองแทนสดย่อย5", CONFIG_SHEET):
            self.assertNotIn(excluded, names)

    def test_each_page_carries_its_own_template(self):
        workbook, _ = self.build()
        found = dict(workbook.writable_pages())
        self.assertEqual(found["เงินสดย่อย6"], PETTY_CASH)
        self.assertEqual(found["เงินฉุกเฉิน3"], EMERGENCY)


class Requesters(unittest.TestCase):
    def test_harvested_from_the_column_most_used_first(self):
        service = FakeService(
            {n: grid_for(n) for n in ("เงินสดย่อย6", "เงินฉุกเฉิน3")},
            {"เงินสดย่อย6": 1, "เงินฉุกเฉิน3": 2},
        )
        found = Workbook(service, "fake-id").requesters()
        self.assertEqual(found[0], "Monny")
        self.assertNotIn("-", found)
        self.assertNotIn("", found)

    def test_a_name_typed_once_shows_up_next_time(self):
        """Why there is no separate list to maintain."""
        grid = grid_for("เงินสดย่อย6")
        grid[20][column_index(PETTY_CASH.requester) - 1] = "พี่นวล"
        grid[20][column_index(PETTY_CASH.description) - 1] = "ค่ารถ"
        service = FakeService({"เงินสดย่อย6": grid}, {"เงินสดย่อย6": 1})
        self.assertIn("พี่นวล", Workbook(service, "fake-id").requesters())

    def test_a_workbook_with_no_pages_yields_no_names(self):
        service = FakeService({}, {"แจกแจง": 1})
        self.assertEqual(Workbook(service, "fake-id").requesters(), [])
