"""Offline tests for the web UI, against fake Sheets and fake OCR.

The property that matters most here has nothing to do with rendering: the
preview step must never write. Several of these assert that directly.
"""

from __future__ import annotations

import datetime as dt
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from fastapi.testclient import TestClient  # noqa: E402

from mousai.page import column_index  # noqa: E402
from mousai.receipt import Reading  # noqa: E402
from mousai.sheets import CONFIG_SHEET, Workbook, WorkbookRef  # noqa: E402
from mousai.templates import PETTY_CASH  # noqa: E402
from mousai.web import OTHER, create_app  # noqa: E402
from test_page import grid_for  # noqa: E402
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


def build(reading=None, with_config=False, grids=None):
    names = [PAGE, EMERGENCY_PAGE, "ย่อย", "ใบรับรองแทนสดย่อย5"]
    service = FakeService(
        grids or {n: grid_for(n) for n in names},
        {n: i for i, n in enumerate(names)},
    )
    if with_config:
        service.ids[CONFIG_SHEET] = 90
        service.grids[CONFIG_SHEET] = [["fund", "active_page"], ["เงินสดย่อย", PAGE]]
    reader = FakeReader(reading)
    return TestClient(create_app(FakeSheets(service), reader)), service, reader


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
        client.post("/confirm", data=fields(page=EMERGENCY_PAGE, amount="780"))
        writes = [b for b in service.batches if any("updateCells" in r for r in b["requests"])]
        columns = {r["updateCells"]["start"]["columnIndex"] for r in writes[0]["requests"]}
        self.assertEqual(columns, set(range(0, 7)))  # A..G, not B..H

    def test_a_sheet_that_is_not_a_page_is_refused(self):
        client, service, _ = build()
        response = client.post("/confirm", data=fields(page="ย่อย"))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(service.batches, [])


class RequesterPicker(unittest.TestCase):
    def test_offers_names_already_used_in_the_column(self):
        client, _, _ = build()
        body = client.get("/").text
        self.assertIn('<option value="Monny"', body)

    def test_always_offers_the_dash_and_a_manual_option(self):
        client, _, _ = build()
        body = client.get("/").text
        self.assertIn('<option value="-"', body)
        self.assertIn(f'<option value="{OTHER}"', body)

    def test_choosing_a_name_writes_that_name(self):
        client, service, _ = build()
        client.post("/confirm", data=fields(requester="Monny"))
        writes = [b for b in service.batches if any("updateCells" in r for r in b["requests"])]
        values = {
            r["updateCells"]["start"]["columnIndex"]:
            r["updateCells"]["rows"][0]["values"][0]["userEnteredValue"]
            for r in writes[0]["requests"]
        }
        self.assertEqual(values[column_index(PETTY_CASH.requester) - 1], {"stringValue": "Monny"})

    def test_a_typed_name_is_used_when_other_is_chosen(self):
        client, service, _ = build()
        client.post("/confirm", data=fields(requester=OTHER, requester_other="พี่นวล"))
        writes = [b for b in service.batches if any("updateCells" in r for r in b["requests"])]
        values = {
            r["updateCells"]["start"]["columnIndex"]:
            r["updateCells"]["rows"][0]["values"][0]["userEnteredValue"]
            for r in writes[0]["requests"]
        }
        self.assertEqual(values[column_index(PETTY_CASH.requester) - 1], {"stringValue": "พี่นวล"})

    def test_other_with_nothing_typed_falls_back_to_the_dash(self):
        client, service, _ = build()
        client.post("/confirm", data=fields(requester=OTHER, requester_other="   "))
        writes = [b for b in service.batches if any("updateCells" in r for r in b["requests"])]
        values = {
            r["updateCells"]["start"]["columnIndex"]:
            r["updateCells"]["rows"][0]["values"][0]["userEnteredValue"]
            for r in writes[0]["requests"]
        }
        self.assertEqual(values[column_index(PETTY_CASH.requester) - 1], {"stringValue": "-"})

    def test_a_new_name_appears_in_the_preview_dropdown(self):
        client, _, _ = build()
        body = client.post("/preview", data=fields(requester=OTHER, requester_other="พี่อ้อ")).text
        self.assertIn('<option value="พี่อ้อ"', body)


class Landing(unittest.TestCase):
    def test_offers_the_camera_on_a_phone(self):
        client, _, _ = build()
        self.assertIn('capture="environment"', client.get("/").text)

    def test_health_reports_the_ocr_backend(self):
        client, _, _ = build()
        self.assertEqual(client.get("/health").json(), {"ok": True, "ocr": "fake"})

    def test_a_workbook_with_no_pages_says_so(self):
        client, _, _ = build(grids={})
        service = FakeService({}, {"ย่อย": 1})
        client = TestClient(create_app(FakeSheets(service), FakeReader()))
        response = client.get("/")
        self.assertEqual(response.status_code, 400)
        self.assertIn("ไม่มีหน้าที่เขียนได้", response.text)


class Preview(unittest.TestCase):
    def test_shows_the_target_row_and_new_balance(self):
        client, _, _ = build()
        response = client.post("/preview", data=fields())
        self.assertEqual(response.status_code, 200)
        self.assertIn("แถว 21", response.text)
        self.assertIn("-2.75", response.text)

    def test_preview_never_writes(self):
        """The whole point of the step."""
        client, service, _ = build()
        client.post("/preview", data=fields())
        self.assertEqual(service.batches, [])
        self.assertEqual(service.value_writes, [])

    def test_shows_the_negative_balance_warning_in_thai(self):
        client, _, _ = build()
        self.assertIn("ติดลบ", client.post("/preview", data=fields()).text)

    def test_shows_rows_remaining(self):
        client, _, _ = build()
        self.assertIn("10 แถว", client.post("/preview", data=fields()).text)

    def test_rejects_a_missing_amount(self):
        client, service, _ = build()
        response = client.post("/preview", data=fields(amount=""))
        self.assertIn("จำนวนเงิน", response.text)
        self.assertEqual(service.batches, [])

    def test_rejects_zero(self):
        client, _, _ = build()
        self.assertEqual(client.post("/preview", data=fields(amount="0")).status_code, 400)


class WithAReceipt(unittest.TestCase):
    READING = Reading(
        amount=23.0,
        date=dt.date(2026, 8, 3),
        description="ค่าขนมปังรับรองลูกค้า",
        notes=["read by a fake"],
    )

    def test_ocr_fills_the_blank_fields(self):
        client, _, reader = build(self.READING)
        response = client.post(
            "/preview",
            data=fields(amount="", description="", entry_date=""),
            files={"receipt": ("bill.jpg", JPEG, "image/jpeg")},
        )
        self.assertEqual(reader.calls, 1)
        self.assertIn("23.0", response.text)
        self.assertIn("read by a fake", response.text)

    def test_what_the_user_typed_beats_what_ocr_read(self):
        client, _, _ = build(self.READING)
        response = client.post(
            "/preview",
            data=fields(amount="99"),
            files={"receipt": ("bill.jpg", JPEG, "image/jpeg")},
        )
        self.assertIn("-78.75", response.text)  # 20.25 - 99

    def test_refuses_a_file_that_is_not_an_image(self):
        client, _, reader = build()
        response = client.post(
            "/preview",
            data=fields(),
            files={"receipt": ("notes.pdf", b"%PDF-1.4", "application/pdf")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(reader.calls, 0)


class Confirm(unittest.TestCase):
    def test_writes_the_entry(self):
        client, service, _ = build()
        response = client.post("/confirm", data=fields(remember=""))
        self.assertEqual(response.status_code, 200)
        self.assertIn("บันทึกแล้ว", response.text)
        writes = [b for b in service.batches if any("updateCells" in r for r in b["requests"])]
        self.assertEqual(len(writes), 1)
        rows = {r["updateCells"]["start"]["rowIndex"] for r in writes[0]["requests"]}
        self.assertEqual(rows, {20})

    def test_remembering_creates_the_hidden_config_tab(self):
        client, service, _ = build()
        client.post("/confirm", data=fields(remember="1"))
        added = [r for b in service.batches for r in b["requests"] if "addSheet" in r]
        self.assertEqual(len(added), 1)
        self.assertTrue(added[0]["addSheet"]["properties"]["hidden"])

    def test_not_remembering_leaves_the_structure_alone(self):
        client, service, _ = build()
        client.post("/confirm", data=fields(remember=""))
        self.assertEqual(
            [r for b in service.batches for r in b["requests"] if "addSheet" in r], []
        )

    def test_a_taken_row_is_refused_and_nothing_is_written(self):
        client, service, _ = build()
        service.grids[PAGE][20][3] = "typed by a human first"
        response = client.post("/confirm", data=fields())
        self.assertEqual(response.status_code, 400)
        self.assertEqual(service.batches, [])

    def test_a_full_page_is_refused(self):
        service = FakeService({"เงินสดย่อย5": grid_for("เงินสดย่อย5")}, {"เงินสดย่อย5": 9})
        client = TestClient(create_app(FakeSheets(service), FakeReader()))
        response = client.post("/confirm", data=fields(page="เงินสดย่อย5"))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(service.batches, [])

    def test_a_broken_date_is_refused(self):
        client, service, _ = build()
        response = client.post("/confirm", data=fields(entry_date="tuesday"))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(service.batches, [])

    def test_recomputes_rather_than_trusting_the_preview(self):
        client, service, _ = build()
        client.post("/confirm", data=fields(amount="5"))
        writes = [b for b in service.batches if any("updateCells" in r for r in b["requests"])]
        values = {
            r["updateCells"]["start"]["columnIndex"]:
            r["updateCells"]["rows"][0]["values"][0]["userEnteredValue"]
            for r in writes[0]["requests"]
        }
        self.assertEqual(values[5], {"numberValue": 5.0})


if __name__ == "__main__":
    unittest.main()
