"""The Review core, without HTTP: what is shown is what gets written.

The web page and the bot both go through `Desk`, so the rule that protects the
Workbook is tested here once, directly, rather than through either front end.
"""

from __future__ import annotations

import datetime as dt
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from mousai.page import PageError, RegionFull  # noqa: E402
from mousai.review import (  # noqa: E402
    PREVIEW_TTL,
    Desk,
    Draft,
    Stale,
    current_first,
    workbook_month,
)
from mousai.sheets import SheetsError, WorkbookRef  # noqa: E402
from mousai.templates import PETTY_CASH  # noqa: E402
from test_page import grid_for, occupy  # noqa: E402
from test_sheets import FakeService  # noqa: E402
from test_web import BOOK, PAGE, Clock, FakeSheets, count_page_reads  # noqa: E402

ON = dt.date(2026, 8, 3)


def desk_for(names=(PAGE,), clock=None):
    service = FakeService({n: grid_for(n) for n in names}, {n: i for i, n in enumerate(names)})
    return Desk(lambda: FakeSheets(service), clock or Clock()), service


def draft(**overrides) -> Draft:
    fields = dict(
        workbook_id=BOOK, page=PAGE, on=ON, description="ค่าขนมปังรับรองลูกค้า", amount=23.0
    )
    fields.update(overrides)
    return Draft(**fields)


def writes(service) -> list:
    return [b for b in service.batches if any("updateCells" in r for r in b["requests"])]


class Reviews(unittest.TestCase):
    def test_a_ready_review_has_cells_and_a_key(self):
        desk, _ = desk_for()
        review = desk.review(draft())
        self.assertTrue(review.ready)
        self.assertEqual(review.row, 21)
        self.assertEqual(review.fund, PETTY_CASH.fund)
        self.assertTrue(review.key)
        self.assertEqual({c["ref"] for c in review.cells}, {f"{c}21" for c in "BCDEFGH"})

    def test_without_an_amount_it_says_where_but_has_nothing_to_confirm(self):
        desk, _ = desk_for()
        review = desk.review(draft(amount=None))
        self.assertFalse(review.ready)
        self.assertEqual(review.row, 21)
        self.assertIsNone(review.key)
        self.assertEqual(review.cells, ())

    def test_a_placeholder_amount_raises_no_negative_balance_warning(self):
        desk, _ = desk_for()
        codes = {w.code for w in desk.review(draft(amount=None)).warnings}
        self.assertNotIn("negative_balance", codes)

    def test_reviewing_never_writes(self):
        desk, service = desk_for()
        desk.review(draft())
        desk.review(draft(amount=None))
        self.assertEqual(service.batches, [])

    def test_repeated_reviews_read_the_page_once(self):
        desk, service = desk_for()
        reads = count_page_reads(service)
        for amount in (1.0, 2.0, 3.0):
            desk.review(draft(amount=amount))
        self.assertEqual(len(reads), 1)

    def test_the_cache_runs_out(self):
        clock = Clock()
        desk, service = desk_for(clock=clock)
        reads = count_page_reads(service)
        desk.review(draft())
        clock.now += PREVIEW_TTL + 1
        desk.review(draft())
        self.assertEqual(len(reads), 2)


class Confirming(unittest.TestCase):
    def test_the_key_of_the_review_writes_those_cells(self):
        desk, service = desk_for()
        key = desk.review(draft()).key
        placement = desk.confirm(draft(), key)
        self.assertEqual(placement.row, 21)
        self.assertEqual(len(writes(service)), 1)

    def test_a_key_for_other_cells_is_stale_and_writes_nothing(self):
        desk, service = desk_for()
        key = desk.review(draft(amount=23.0)).key
        with self.assertRaises(Stale) as caught:
            desk.confirm(draft(amount=99.0), key)
        self.assertEqual(caught.exception.notice.code, "preview_stale")
        self.assertEqual(service.batches, [])

    def test_someone_writing_first_makes_the_review_stale(self):
        """The Review came from a cached read; confirm reads again."""
        desk, service = desk_for()
        key = desk.review(draft()).key
        occupy(service.grids[PAGE], 21, PETTY_CASH, "typed by a human first", 10.25)
        with self.assertRaises(Stale):
            desk.confirm(draft(), key)
        self.assertEqual(service.batches, [])

    def test_after_any_confirm_the_next_review_reads_afresh(self):
        desk, service = desk_for()
        reads = count_page_reads(service)
        desk.review(draft())
        with self.assertRaises(Stale):
            desk.confirm(draft(), "not the key")
        desk.review(draft())
        # One cached read for the first Review, one fresh for confirm, and one
        # more because confirm forgot the cache.
        self.assertEqual(len(reads), 3)

    def test_an_unready_draft_cannot_be_confirmed(self):
        desk, service = desk_for()
        with self.assertRaises(PageError):
            desk.confirm(draft(amount=None), "anything")
        self.assertEqual(service.batches, [])

    def test_remembering_the_page_is_part_of_the_confirm(self):
        desk, service = desk_for()
        key = desk.review(draft()).key
        desk.confirm(draft(), key, remember=True)
        self.assertTrue(any("addSheet" in r for b in service.batches for r in b["requests"]))


class CurrentWorkbook(unittest.TestCase):
    """The current Workbook is the latest month in a name, not the latest edit."""

    def test_reads_the_month_from_the_name(self):
        cases = {
            "เบิกจ่ายเงินสด สิงหาคม26": dt.date(2026, 8, 1),
            "เบิกจ่ายเงินสด กันยายน26": dt.date(2026, 9, 1),
            "เบิกจ่ายเงินสด กันยายน 2569": dt.date(2026, 9, 1),
            "เบิกจ่ายเงินสด ธันวาคม69": dt.date(2026, 12, 1),
            "เงินสด ม.ค. 27": dt.date(2027, 1, 1),
            "สำเนาทดสอบ": None,
        }
        for title, month in cases.items():
            with self.subTest(title=title):
                self.assertEqual(workbook_month(title), month)

    def test_an_edit_to_last_month_does_not_make_it_current(self):
        """Drive lists newest-modified first; August was touched most recently."""
        books = [
            WorkbookRef(id="aug", title="เบิกจ่ายเงินสด สิงหาคม26", modified="2026-09-03T09:00:00Z"),
            WorkbookRef(id="copy", title="สำเนาทดสอบ", modified="2026-09-02T09:00:00Z"),
            WorkbookRef(id="sep", title="เบิกจ่ายเงินสด กันยายน26", modified="2026-09-01T09:00:00Z"),
        ]
        self.assertEqual([b.id for b in current_first(books)], ["sep", "aug", "copy"])

    def test_the_desk_offers_the_current_month_first(self):
        service = FakeService({PAGE: grid_for(PAGE)}, {PAGE: 0})
        books = [
            WorkbookRef(id="aug", title="เบิกจ่ายเงินสด สิงหาคม26", modified="2026-09-03T09:00:00Z"),
            WorkbookRef(id="sep", title="เบิกจ่ายเงินสด กันยายน26", modified="2026-09-01T09:00:00Z"),
        ]
        desk = Desk(lambda: FakeSheets(service, books), Clock())
        self.assertEqual(desk.workbooks()[0].id, "sep")

    def test_a_workbook_with_no_month_is_still_accepted(self):
        service = FakeService({PAGE: grid_for(PAGE)}, {PAGE: 0})
        books = [WorkbookRef(id="copy", title="สำเนาทดสอบ", modified="2026-09-02T09:00:00Z")]
        desk = Desk(lambda: FakeSheets(service, books), Clock())
        desk.check_workbook("copy")


class Refusals(unittest.TestCase):
    def test_a_full_page_is_refused_by_review_and_confirm(self):
        desk, service = desk_for(names=("เงินสดย่อย5",))
        full = draft(page="เงินสดย่อย5")
        with self.assertRaises(RegionFull):
            desk.review(full)
        with self.assertRaises(RegionFull):
            desk.confirm(full, "anything")
        self.assertEqual(service.batches, [])

    def test_a_workbook_outside_the_folder_is_refused(self):
        desk, service = desk_for()
        stranger = draft(workbook_id="1QB-not-in-the-folder")
        for attempt in (lambda: desk.review(stranger), lambda: desk.confirm(stranger, "k")):
            with self.assertRaises(SheetsError) as caught:
                attempt()
            self.assertEqual(caught.exception.notice.code, "unknown_workbook")
        self.assertEqual(service.batches, [])

    def test_a_sheet_that_is_not_a_page_is_refused(self):
        desk, _ = desk_for()
        with self.assertRaises(PageError) as caught:
            desk.review(draft(page="ย่อย"))
        self.assertEqual(caught.exception.notice.code, "unknown_page")


if __name__ == "__main__":
    unittest.main()
