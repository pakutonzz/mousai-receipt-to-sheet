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

from mousai.receipt import Reading  # noqa: E402
from mousai.sheets import CONFIG_SHEET, Workbook, WorkbookRef  # noqa: E402
from mousai.web import create_app  # noqa: E402
from test_page import grid_for  # noqa: E402
from test_sheets import FakeService  # noqa: E402

PAGE = "เงินสดย่อย6"
BOOK = "book-1"
JPEG = b"\xff\xd8\xff\xe0 pretend jpeg"


class FakeSheets:
    def __init__(self, service):
        self._service = service

    def workbooks(self, folder_id=None):
        return [WorkbookRef(id=BOOK, title="สิงหาคม26", modified="2026-09-01T00:00:00Z")]

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


def build(reading=None, with_config=False):
    service = FakeService({PAGE: grid_for(PAGE)}, {PAGE: 42})
    if with_config:
        service.ids[CONFIG_SHEET] = 7
        service.grids[CONFIG_SHEET] = [["fund", "active_page"], ["เงินสดย่อย", PAGE]]
    reader = FakeReader(reading)
    client = TestClient(create_app(FakeSheets(service), reader))
    return client, service, reader


def manual_fields(**overrides):
    fields = {
        "fund": "เงินสดย่อย",
        "workbook_id": BOOK,
        "page": PAGE,
        "entry_date": "2026-08-03",
        "description": "ค่าขนมปังรับรองลูกค้า",
        "amount": "23",
        "requester": "-",
        "note": "",
    }
    fields.update(overrides)
    return fields


class Landing(unittest.TestCase):
    def test_form_lists_both_funds_and_the_workbook(self):
        client, _, _ = build()
        response = client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("เงินสดย่อย", response.text)
        self.assertIn("เงินฉุกเฉิน", response.text)
        self.assertIn("สิงหาคม26", response.text)

    def test_offers_the_camera_on_a_phone(self):
        client, _, _ = build()
        self.assertIn('capture="environment"', client.get("/").text)

    def test_health_reports_the_ocr_backend(self):
        client, _, _ = build()
        self.assertEqual(client.get("/health").json(), {"ok": True, "ocr": "fake"})


class Preview(unittest.TestCase):
    def test_shows_the_target_row_and_new_balance(self):
        client, service, _ = build()
        response = client.post("/preview", data=manual_fields())
        self.assertEqual(response.status_code, 200)
        self.assertIn("แถว 21", response.text)
        self.assertIn("-2.75", response.text)

    def test_preview_never_writes(self):
        """The whole point of the step."""
        client, service, _ = build()
        client.post("/preview", data=manual_fields())
        self.assertEqual(service.batches, [])
        self.assertEqual(service.value_writes, [])

    def test_shows_the_negative_balance_warning(self):
        client, _, _ = build()
        self.assertIn("ติดลบ", _warnings(client.post("/preview", data=manual_fields()).text))

    def test_shows_rows_remaining(self):
        client, _, _ = build()
        self.assertIn("10 แถว", client.post("/preview", data=manual_fields()).text)

    def test_rejects_a_missing_amount(self):
        client, service, _ = build()
        response = client.post("/preview", data=manual_fields(amount=""))
        self.assertIn("จำนวนเงิน", response.text)
        self.assertEqual(service.batches, [])

    def test_rejects_zero(self):
        client, _, _ = build()
        self.assertEqual(client.post("/preview", data=manual_fields(amount="0")).status_code, 400)

    def test_asks_which_page_when_nothing_is_remembered(self):
        client, _, _ = build()
        response = client.post("/preview", data=manual_fields(page=""))
        self.assertIn("เลือกหน้าที่จะบันทึก", response.text)
        self.assertIn(PAGE, response.text)

    def test_uses_the_remembered_page(self):
        client, _, _ = build(with_config=True)
        response = client.post("/preview", data=manual_fields(page=""))
        self.assertIn("แถว 21", response.text)


def _warnings(html: str) -> str:
    return html


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
            data=manual_fields(amount="", description="", entry_date=""),
            files={"receipt": ("bill.jpg", JPEG, "image/jpeg")},
        )
        self.assertEqual(reader.calls, 1)
        self.assertIn("23.0", response.text)
        self.assertIn("ค่าขนมปังรับรองลูกค้า", response.text)
        self.assertIn("read by a fake", response.text)

    def test_what_the_user_typed_beats_what_ocr_read(self):
        client, _, _ = build(self.READING)
        response = client.post(
            "/preview",
            data=manual_fields(amount="99"),
            files={"receipt": ("bill.jpg", JPEG, "image/jpeg")},
        )
        self.assertIn("99", response.text)
        self.assertIn("-78.75", response.text)  # 20.25 - 99

    def test_ocr_reading_nothing_still_reaches_the_preview(self):
        client, _, _ = build(Reading(notes=["could not read"]))
        response = client.post(
            "/preview",
            data=manual_fields(),
            files={"receipt": ("bill.jpg", JPEG, "image/jpeg")},
        )
        self.assertIn("แถว 21", response.text)

    def test_refuses_a_file_that_is_not_an_image(self):
        client, _, reader = build()
        response = client.post(
            "/preview",
            data=manual_fields(),
            files={"receipt": ("notes.pdf", b"%PDF-1.4", "application/pdf")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(reader.calls, 0)


class Confirm(unittest.TestCase):
    def test_writes_the_entry(self):
        client, service, _ = build()
        response = client.post("/confirm", data=manual_fields(remember=""))
        self.assertEqual(response.status_code, 200)
        self.assertIn("บันทึกแล้ว", response.text)

        writes = [b for b in service.batches if any("updateCells" in r for r in b["requests"])]
        self.assertEqual(len(writes), 1)
        rows = {r["updateCells"]["start"]["rowIndex"] for r in writes[0]["requests"]}
        self.assertEqual(rows, {20})  # row 21, zero-indexed

    def test_remembering_the_page_creates_the_hidden_config_tab(self):
        client, service, _ = build()
        client.post("/confirm", data=manual_fields(remember="1"))
        added = [r for b in service.batches for r in b["requests"] if "addSheet" in r]
        self.assertEqual(len(added), 1)
        self.assertTrue(added[0]["addSheet"]["properties"]["hidden"])

    def test_not_remembering_leaves_the_workbook_structure_alone(self):
        client, service, _ = build()
        client.post("/confirm", data=manual_fields(remember=""))
        added = [r for b in service.batches for r in b["requests"] if "addSheet" in r]
        self.assertEqual(added, [])

    def test_a_taken_row_is_refused_and_nothing_is_written(self):
        client, service, _ = build()
        service.grids[PAGE][20][3] = "typed by a human first"
        response = client.post("/confirm", data=manual_fields())
        self.assertEqual(response.status_code, 400)
        self.assertIn("21", response.text)
        self.assertEqual(service.batches, [])

    def test_a_full_page_is_refused(self):
        service = FakeService({"เงินสดย่อย5": grid_for("เงินสดย่อย5")}, {"เงินสดย่อย5": 9})
        client = TestClient(create_app(FakeSheets(service), FakeReader()))
        response = client.post(
            "/confirm", data=manual_fields(page="เงินสดย่อย5")
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(service.batches, [])

    def test_a_broken_date_is_refused(self):
        client, service, _ = build()
        response = client.post("/confirm", data=manual_fields(entry_date="tuesday"))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(service.batches, [])

    def test_recomputes_rather_than_trusting_the_preview(self):
        """An edited amount at confirm time must change the balance written."""
        client, service, _ = build()
        client.post("/confirm", data=manual_fields(amount="5"))
        writes = [b for b in service.batches if any("updateCells" in r for r in b["requests"])]
        values = {
            r["updateCells"]["start"]["columnIndex"]:
            r["updateCells"]["rows"][0]["values"][0]["userEnteredValue"]
            for r in writes[0]["requests"]
        }
        self.assertEqual(values[5], {"numberValue": 5.0})  # column F


if __name__ == "__main__":
    unittest.main()
