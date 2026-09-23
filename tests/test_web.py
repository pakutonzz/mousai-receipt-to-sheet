"""Offline tests for the web UI, against fake Sheets and fake OCR.

The property that matters most here has nothing to do with rendering: nothing
is written until a person has seen the exact cells and pressed Confirm. The live
preview must never write, and Confirm must refuse cells that differ from the
ones the preview showed. Several of these assert that directly.
"""

from __future__ import annotations

import datetime as dt
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from fastapi.testclient import TestClient  # noqa: E402

from mousai.page import column_index  # noqa: E402
from mousai.messages import Notice  # noqa: E402
from mousai.receipt import Reading  # noqa: E402
from mousai.sheets import CONFIG_SHEET, Workbook, WorkbookRef  # noqa: E402
from mousai.templates import PETTY_CASH  # noqa: E402
from mousai.web import OTHER, PREVIEW_TTL, create_app  # noqa: E402
from test_page import grid_for, occupy  # noqa: E402
from test_sheets import FakeService  # noqa: E402

PAGE = "เงินสดย่อย6"
EMERGENCY_PAGE = "เงินฉุกเฉิน3"
BOOK = "book-1"
JPEG = b"\xff\xd8\xff\xe0 pretend jpeg"


class FakeSheets:
    def __init__(self, service, books=None):
        self._service = service
        self._books = books or [
            WorkbookRef(id=BOOK, title="สิงหาคม26", modified="2026-09-01T00:00:00Z")
        ]

    def workbooks(self, folder_id=None):
        return self._books

    def open(self, spreadsheet_id):
        return Workbook(self._service, spreadsheet_id)


class FakeReader:
    def __init__(self, reading=None, name="fake"):
        self.name = name
        self._reading = reading or Reading()
        self.calls = 0

    def read_image(self, data, mime):
        self.calls += 1
        return self._reading


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def build(reading=None, with_config=False, grids=None, clock=None):
    names = [PAGE, EMERGENCY_PAGE, "ย่อย", "ใบรับรองแทนสดย่อย5"]
    service = FakeService(
        grids or {n: grid_for(n) for n in names},
        {n: i for i, n in enumerate(names)},
    )
    if with_config:
        service.ids[CONFIG_SHEET] = 90
        service.grids[CONFIG_SHEET] = [["fund", "active_page"], ["เงินสดย่อย", PAGE]]
    reader = FakeReader(reading)
    app = create_app(FakeSheets(service), reader, clock=clock or Clock())
    return TestClient(app), service, reader


def fields(**overrides):
    base = {
        "workbook_id": BOOK,
        "page": PAGE,
        "entry_date": "2026-08-03",
        "description": "ค่าขนมปังรับรองลูกค้า",
        "amount": "23",
        "requester": "-",
        "requester_other": "",
        "note": "",
    }
    base.update(overrides)
    return base


def preview(client, **overrides) -> dict:
    return client.post("/api/preview", data=fields(**overrides)).json()


def confirm(client, remember="", **overrides):
    """What the page does: preview these fields, then confirm with that key."""
    key = preview(client, **overrides).get("key", "")
    return client.post(
        "/confirm",
        data=fields(key=key, remember=remember, **overrides),
        follow_redirects=False,
    )


def written(service) -> dict:
    """Column index -> value, for the single Entry written."""
    writes = [b for b in service.batches if any("updateCells" in r for r in b["requests"])]
    assert len(writes) == 1, writes
    return {
        r["updateCells"]["start"]["columnIndex"]: r["updateCells"]["rows"][0]["values"][0][
            "userEnteredValue"
        ]
        for r in writes[0]["requests"]
    }


def nothing_written(service) -> bool:
    return service.batches == [] and service.value_writes == []


def cell(body: dict, ref: str) -> str | None:
    return next((c["value"] for c in body.get("cells", []) if c["ref"] == ref), None)


def rendered_value(html: str, element_id: str) -> str:
    """The value a browser would submit for an input, as the page rendered it."""
    match = re.search(rf'<input[^>]*id="{element_id}"[^>]*value="([^"]*)"', html)
    if match is None:
        raise AssertionError(f"no input #{element_id} with a value attribute")
    return match.group(1)


def count_page_reads(service) -> list[str]:
    reads: list[str] = []
    original = service.get

    def counting(**kwargs):
        if kwargs.get("range") and not kwargs["range"].startswith(CONFIG_SHEET):
            reads.append(kwargs["range"])
        return original(**kwargs)

    service.get = counting
    return reads


class OnePage(unittest.TestCase):
    """The photo, the fields, the cells and the button all live on the home page."""

    def test_home_has_the_camera_the_cells_and_the_button(self):
        client, _, _ = build()
        body = client.get("/").text
        self.assertIn('capture="environment"', body)
        self.assertIn("เซลล์ที่จะเขียน", body)
        self.assertIn('id="confirm"', body)

    def test_review_starts_disabled_until_a_preview_arrives(self):
        client, _, _ = build()
        body = client.get("/").text
        self.assertRegex(body, r'<button[^>]*id="review"[^>]*disabled')

    def test_the_only_way_to_write_is_inside_the_review_popup(self):
        """The page itself has no submit button; the popup has the only one."""
        client, _, _ = build()
        body = client.get("/").text
        dialog = re.search(r'<dialog id="review-dialog".*?</dialog>', body, re.S)
        self.assertIsNotNone(dialog)
        outside = body.replace(dialog.group(0), "")
        self.assertEqual(len(re.findall(r'type="submit"', dialog.group(0))), 1)
        form = re.search(r'<form id="entry".*?</form>', outside, re.S).group(0)
        self.assertNotIn('type="submit"', form)
        self.assertIn('id="confirm"', dialog.group(0))

    def test_cells_and_warnings_live_only_in_the_popup(self):
        """The page stays short on a phone; the popup is where you check."""
        client, _, _ = build()
        body = client.get("/").text
        dialog = re.search(r'<dialog id="review-dialog".*?</dialog>', body, re.S).group(0)
        page = body.replace(dialog, "")
        self.assertIn('id="r-cells"', dialog)
        self.assertIn('id="r-warnings"', dialog)
        self.assertNotIn("<table class=\"rows mono\"", page)
        self.assertNotIn("เซลล์ที่จะเขียน", page.split("<script>")[0].split("<noscript>")[0])
        self.assertNotIn('id="warnings"', page)

    def test_remember_is_chosen_in_the_popup(self):
        client, _, _ = build()
        dialog = re.search(
            r'<dialog id="review-dialog".*?</dialog>', client.get("/").text, re.S
        ).group(0)
        self.assertIn('name="remember"', dialog)

    def test_the_photo_is_never_posted_with_confirm(self):
        """The file input has no name, so the form cannot carry the image."""
        client, _, _ = build()
        tag = re.search(r'<input type="file"[^>]*>', client.get("/").text).group(0)
        self.assertNotIn("name=", tag)

    def test_the_old_two_step_route_is_gone(self):
        client, _, _ = build()
        self.assertEqual(client.post("/preview", data=fields()).status_code, 404)

    def test_health_reports_the_ocr_backend(self):
        client, _, _ = build()
        self.assertEqual(client.get("/health").json(), {"ok": True, "ocr": "fake"})

    def test_a_workbook_with_no_pages_says_so(self):
        service = FakeService({}, {"ย่อย": 1})
        client = TestClient(create_app(FakeSheets(service), FakeReader()))
        response = client.get("/")
        self.assertEqual(response.status_code, 400)
        self.assertIn("ไม่มีหน้าที่เขียนได้", response.text)


class PagePicker(unittest.TestCase):
    def test_lists_pages_from_every_fund_not_just_a_category(self):
        client, _, _ = build()
        body = client.get("/").text
        self.assertIn(PAGE, body)
        self.assertIn(EMERGENCY_PAGE, body)
        self.assertIn('<optgroup label="เงินสดย่อย"', body)
        self.assertIn('<optgroup label="เงินฉุกเฉิน"', body)

    def test_does_not_offer_ledgers_or_certificates(self):
        client, _, _ = build()
        body = client.get("/").text
        self.assertNotIn(">ใบรับรองแทนสดย่อย5", body)
        self.assertNotIn('value="ย่อย"', body)

    def test_marks_the_remembered_page(self):
        client, _, _ = build(with_config=True)
        self.assertIn("●", client.get("/").text)

    def test_api_serves_the_pages_for_another_workbook(self):
        client, _, _ = build()
        data = client.get("/api/pages", params={"workbook_id": BOOK}).json()
        funds = [g["fund"] for g in data["groups"]]
        self.assertEqual(funds, ["เงินสดย่อย", "เงินฉุกเฉิน"])

    def test_the_fund_follows_from_the_page(self):
        """Picking an emergency Page uses the A-column layout, unprompted."""
        client, service, _ = build()
        confirm(client, page=EMERGENCY_PAGE, amount="780")
        self.assertEqual(set(written(service)), set(range(0, 7)))  # A..G, not B..H

    def test_a_sheet_that_is_not_a_page_is_refused(self):
        client, service, _ = build()
        response = client.post("/confirm", data=fields(page="ย่อย"))
        self.assertEqual(response.status_code, 400)
        self.assertTrue(nothing_written(service))


class RequesterPicker(unittest.TestCase):
    def test_offers_names_already_used_in_the_column(self):
        client, _, _ = build()
        self.assertIn('<option value="Monny"', client.get("/").text)

    def test_always_offers_the_dash_and_a_manual_option(self):
        client, _, _ = build()
        body = client.get("/").text
        self.assertIn('<option value="-"', body)
        self.assertIn(f'<option value="{OTHER}"', body)

    def test_choosing_a_name_writes_that_name(self):
        client, service, _ = build()
        confirm(client, requester="Monny")
        column = column_index(PETTY_CASH.requester) - 1
        self.assertEqual(written(service)[column], {"stringValue": "Monny"})

    def test_a_typed_name_is_used_when_other_is_chosen(self):
        client, service, _ = build()
        confirm(client, requester=OTHER, requester_other="พี่นวล")
        column = column_index(PETTY_CASH.requester) - 1
        self.assertEqual(written(service)[column], {"stringValue": "พี่นวล"})

    def test_other_with_nothing_typed_falls_back_to_the_dash(self):
        client, service, _ = build()
        confirm(client, requester=OTHER, requester_other="   ")
        column = column_index(PETTY_CASH.requester) - 1
        self.assertEqual(written(service)[column], {"stringValue": "-"})

    def test_a_typed_name_shows_in_the_cells(self):
        client, _, _ = build()
        body = preview(client, requester=OTHER, requester_other="พี่อ้อ")
        self.assertEqual(cell(body, "H21"), "พี่อ้อ")


class LivePreview(unittest.TestCase):
    def test_shows_the_target_row_and_new_balance(self):
        client, _, _ = build()
        body = preview(client)
        self.assertTrue(body["ready"])
        self.assertEqual(body["row"], 21)
        self.assertEqual(body["previous_balance"], 20.25)
        self.assertAlmostEqual(body["balance"], -2.75)

    def test_preview_never_writes(self):
        """The whole point of the step."""
        client, service, _ = build()
        for amount in ("2", "23", "230"):
            preview(client, amount=amount)
        self.assertTrue(nothing_written(service))

    def test_the_cells_follow_the_fields(self):
        client, _, _ = build()
        first = preview(client, amount="23", description="ค่ากาแฟ")
        second = preview(client, amount="40", description="ค่าน้ำ")
        self.assertEqual(cell(first, "F21"), "23.00")
        self.assertEqual(cell(second, "F21"), "40.00")
        self.assertEqual(cell(second, "D21"), "ค่าน้ำ")
        self.assertNotEqual(first["key"], second["key"])

    def test_the_same_fields_give_the_same_key(self):
        client, _, _ = build()
        self.assertEqual(preview(client)["key"], preview(client)["key"])

    def test_shows_the_negative_balance_warning_in_thai(self):
        client, _, _ = build()
        self.assertTrue(any("ติดลบ" in w for w in preview(client)["warnings"]))

    def test_shows_rows_remaining(self):
        client, _, _ = build()
        self.assertEqual(preview(client)["rows_remaining"], 10)

    def test_without_an_amount_it_says_where_but_offers_nothing_to_confirm(self):
        client, _, _ = build()
        body = preview(client, amount="")
        self.assertFalse(body["ready"])
        self.assertEqual(body["row"], 21)
        self.assertNotIn("key", body)
        self.assertNotIn("cells", body)
        self.assertIn("กรอกจำนวนเงิน", body["message"])

    def test_a_zero_amount_is_not_ready_either(self):
        client, _, _ = build()
        self.assertFalse(preview(client, amount="0")["ready"])

    def test_a_full_page_is_reported_before_an_amount_is_typed(self):
        service = FakeService({"เงินสดย่อย5": grid_for("เงินสดย่อย5")}, {"เงินสดย่อย5": 9})
        client = TestClient(create_app(FakeSheets(service), FakeReader()))
        response = client.post("/api/preview", data=fields(page="เงินสดย่อย5", amount=""))
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_a_sheet_that_is_not_a_page_is_refused(self):
        client, _, _ = build()
        response = client.post("/api/preview", data=fields(page="ย่อย"))
        self.assertEqual(response.status_code, 400)

    def test_a_broken_date_is_refused(self):
        client, _, _ = build()
        response = client.post("/api/preview", data=fields(entry_date="tuesday"))
        self.assertEqual(response.status_code, 400)


class PreviewCache(unittest.TestCase):
    """Typing must not become one Sheets read per pause."""

    def test_repeated_previews_read_the_page_once(self):
        client, service, _ = build()
        reads = count_page_reads(service)
        for amount in ("2", "23", "230", "2300"):
            preview(client, amount=amount)
        self.assertEqual(len(reads), 1)

    def test_the_cache_expires(self):
        clock = Clock()
        client, service, _ = build(clock=clock)
        reads = count_page_reads(service)
        preview(client)
        clock.now += PREVIEW_TTL + 1
        preview(client)
        self.assertEqual(len(reads), 2)

    def test_each_page_has_its_own_read(self):
        client, service, _ = build()
        reads = count_page_reads(service)
        preview(client)
        preview(client, page=EMERGENCY_PAGE)
        self.assertEqual(len(reads), 2)

    def test_confirm_never_trusts_the_cache(self):
        """Someone types into row 21 after the preview was cached. Confirm reads
        the Page again, sees the row gone, and writes nothing."""
        client, service, _ = build()
        key = preview(client)["key"]
        occupy(service.grids[PAGE], 21, PETTY_CASH, "typed by a human first", 10.25)
        response = client.post("/confirm", data=fields(key=key), follow_redirects=False)
        self.assertEqual(response.status_code, 409)
        self.assertTrue(nothing_written(service))

    def test_a_save_clears_the_cache_for_that_page(self):
        client, service, _ = build()
        confirm(client)
        # The fake does not apply writes, so apply this one by hand.
        occupy(service.grids[PAGE], 21, PETTY_CASH, "ค่าขนมปังรับรองลูกค้า", -2.75)
        self.assertEqual(preview(client)["row"], 22)


class ReadingAReceipt(unittest.TestCase):
    NEW_YEAR = Reading(
        amount=1300.0,
        date=dt.date(2025, 1, 1),
        notes=[Notice("date_read", {"text": "1 มกราคม 2025"})],
    )

    def read(self, client, name="bill.jpg", data=JPEG, mime="image/jpeg"):
        return client.post("/api/read", files={"receipt": (name, data, mime)})

    def test_returns_what_it_read_for_the_fields(self):
        client, _, reader = build(self.NEW_YEAR)
        body = self.read(client).json()
        self.assertEqual(reader.calls, 1)
        self.assertEqual(body["amount"], 1300.0)
        self.assertEqual(body["date"], "2025-01-01")
        self.assertEqual(body["notes"], ["วันที่: อ่านได้ 1 มกราคม 2025"])

    def test_a_blank_reading_is_not_an_error(self):
        client, _, _ = build(Reading(notes=[Notice("ocr_no_text")]))
        response = self.read(client)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["amount"])
        self.assertIsNone(response.json()["date"])

    def test_reading_never_writes(self):
        client, service, _ = build(self.NEW_YEAR)
        self.read(client)
        self.assertTrue(nothing_written(service))

    def test_refuses_a_file_that_is_not_an_image(self):
        client, _, reader = build()
        response = self.read(client, "notes.pdf", b"%PDF-1.4", "application/pdf")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(reader.calls, 0)

    def test_refuses_an_image_that_is_too_large(self):
        client, _, reader = build()
        response = self.read(client, data=b"\xff" * (12 * 1024 * 1024 + 1))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(reader.calls, 0)


class ReceiptDates(unittest.TestCase):
    """The date printed on a receipt has to reach the cells.

    It once didn't: the form pre-filled today, and any filled-in date beat OCR,
    so today always won. The field now starts blank, and blank means today only
    when nothing better is known.
    """

    def test_the_form_leaves_the_date_for_the_receipt(self):
        client, _, _ = build()
        self.assertEqual(rendered_value(client.get("/").text, "entry_date"), "")

    def test_the_receipt_date_reaches_the_cells(self):
        client, _, _ = build()
        self.assertEqual(cell(preview(client, entry_date="2025-01-01"), "B21"), "01/01/2025")

    def test_an_old_receipt_is_flagged_not_silently_filed(self):
        """A date months before the row above is exactly what a person should
        look at twice, so the backdated warning has to fire."""
        client, _, _ = build()
        body = preview(client, entry_date="2025-01-01")
        self.assertTrue(any("ย้อนหลังกว่าแถวบน" in w for w in body["warnings"]))

    def test_no_date_anywhere_means_today(self):
        client, _, _ = build()
        body = preview(client, entry_date="")
        self.assertEqual(cell(body, "B21"), f"{dt.date.today():%d/%m/%Y}")

    def test_a_refused_confirm_does_not_freeze_today_into_the_form(self):
        """Otherwise the next photo's date would lose to a date nobody chose."""
        client, _, _ = build()
        response = client.post("/confirm", data=fields(entry_date="", key="stale"))
        self.assertEqual(rendered_value(response.text, "entry_date"), "")


class Confirm(unittest.TestCase):
    def test_writes_the_entry_and_comes_back_home(self):
        client, service, _ = build()
        response = confirm(client)
        self.assertEqual(response.status_code, 303)
        rows = {
            r["updateCells"]["start"]["rowIndex"]
            for b in service.batches
            for r in b["requests"]
            if "updateCells" in r
        }
        self.assertEqual(rows, {20})
        home = client.get(response.headers["location"]).text
        self.assertIn("บันทึกแล้ว", home)
        self.assertIn("แถว <strong>21</strong>", home)

    def test_without_a_preview_nothing_is_written(self):
        client, service, _ = build()
        response = client.post("/confirm", data=fields(), follow_redirects=False)
        self.assertEqual(response.status_code, 409)
        self.assertTrue(nothing_written(service))

    def test_a_key_for_other_cells_is_refused(self):
        """The preview showed 23 baht; the form now says 99."""
        client, service, _ = build()
        key = preview(client, amount="23")["key"]
        response = client.post(
            "/confirm", data=fields(amount="99", key=key), follow_redirects=False
        )
        self.assertEqual(response.status_code, 409)
        self.assertTrue(nothing_written(service))

    def test_a_refused_confirm_keeps_every_field_and_says_why(self):
        client, _, _ = build()
        response = client.post(
            "/confirm",
            data=fields(
                amount="99",
                description="ค่ากาแฟ",
                requester=OTHER,
                requester_other="พี่นวล",
                key="stale",
            ),
        )
        body = response.text
        self.assertIn("เปลี่ยนไประหว่างที่ตรวจสอบ", body)
        self.assertEqual(rendered_value(body, "amount"), "99")
        self.assertEqual(rendered_value(body, "description"), "ค่ากาแฟ")
        self.assertEqual(rendered_value(body, "entry_date"), "2026-08-03")
        self.assertIn('<option value="พี่นวล" selected', body)

    def test_posting_the_same_confirm_twice_writes_once(self):
        """A double tap, or a resend. The first write moves the free row, so the
        second key no longer matches."""
        client, service, _ = build()
        key = preview(client)["key"]
        client.post("/confirm", data=fields(key=key), follow_redirects=False)
        occupy(service.grids[PAGE], 21, PETTY_CASH, "ค่าขนมปังรับรองลูกค้า", -2.75)
        second = client.post("/confirm", data=fields(key=key), follow_redirects=False)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(
            len([b for b in service.batches if any("updateCells" in r for r in b["requests"])]),
            1,
        )

    def test_remembering_creates_the_hidden_config_tab(self):
        client, service, _ = build()
        confirm(client, remember="1")
        added = [r for b in service.batches for r in b["requests"] if "addSheet" in r]
        self.assertEqual(len(added), 1)
        self.assertTrue(added[0]["addSheet"]["properties"]["hidden"])

    def test_not_remembering_leaves_the_structure_alone(self):
        client, service, _ = build()
        confirm(client, remember="")
        self.assertEqual(
            [r for b in service.batches for r in b["requests"] if "addSheet" in r], []
        )

    def test_a_full_page_is_refused(self):
        service = FakeService({"เงินสดย่อย5": grid_for("เงินสดย่อย5")}, {"เงินสดย่อย5": 9})
        client = TestClient(create_app(FakeSheets(service), FakeReader()))
        response = client.post("/confirm", data=fields(page="เงินสดย่อย5"))
        self.assertEqual(response.status_code, 400)
        self.assertTrue(nothing_written(service))

    def test_a_broken_date_is_refused(self):
        client, service, _ = build()
        response = client.post("/confirm", data=fields(entry_date="tuesday"))
        self.assertEqual(response.status_code, 400)
        self.assertTrue(nothing_written(service))

    def test_writes_what_the_preview_showed(self):
        client, service, _ = build()
        confirm(client, amount="5")
        self.assertEqual(written(service)[5], {"numberValue": 5.0})


class CellPreview(unittest.TestCase):
    """The 'cells to be written' table is for a human, not for a machine."""

    def test_the_balance_shows_the_number_not_the_formula(self):
        client, _, _ = build()
        body = preview(client)
        self.assertEqual(cell(body, "G21"), "-2.75")
        self.assertNotIn("=G20-F21", str(body))

    def test_the_date_shows_as_a_date_not_a_serial(self):
        client, _, _ = build()
        body = preview(client)
        self.assertEqual(cell(body, "B21"), "03/08/2026")
        self.assertNotIn("46237", str(body))

    def test_money_shows_two_decimals(self):
        client, _, _ = build()
        self.assertEqual(cell(preview(client, amount="2061"), "F21"), "2,061.00")

    def test_a_formula_is_still_what_gets_written(self):
        """Display only: ADR 0002 says the balance must stay a live formula."""
        client, service, _ = build()
        confirm(client)
        self.assertIn({"formulaValue": "=G20-F21"}, written(service).values())

    def test_the_emergency_layout_humanises_its_own_columns(self):
        client, _, _ = build()
        body = preview(client, page=EMERGENCY_PAGE, amount="780")
        self.assertEqual(cell(body, "F29"), "823.25")
        self.assertEqual(cell(body, "A29"), "03/08/2026")


if __name__ == "__main__":
    unittest.main()
