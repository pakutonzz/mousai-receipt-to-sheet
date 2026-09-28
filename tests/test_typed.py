"""Typed corrections and text-only entries: the rules, and the model's checks."""

from __future__ import annotations

import datetime as dt
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mousai.review import Draft  # noqa: E402
from mousai.typed import (  # noqa: E402
    Changes,
    OllamaInterpreter,
    RuleInterpreter,
    detect,
    resolve_page,
)

TODAY = dt.date(2026, 8, 20)
PAGES = ["เงินสดย่อย5", "เงินสดย่อย6", "เงินฉุกเฉิน3"]
REQUESTERS = ["Aor", "มน", "หมอเก่ง"]


def correct(text, interpreter=None):
    interpreter = interpreter or RuleInterpreter()
    return interpreter.correction(text, pages=PAGES, requesters=REQUESTERS, today=TODAY)


def said(changes: Changes) -> dict:
    return {k: v for k, v in changes.__dict__.items() if v is not None}


class RuleEntries(unittest.TestCase):
    def entry(self, text):
        return RuleInterpreter().entry(text, TODAY)

    def test_one_number_is_the_amount_and_the_rest_the_description(self):
        entry = self.entry("ค่าน้ำแข็ง 45")
        self.assertEqual((entry.amount, entry.description, entry.on), (45.0, "ค่าน้ำแข็ง", TODAY))

    def test_a_relative_day(self):
        entry = self.entry("ค่าส่งของ 60 เมื่อวาน")
        self.assertEqual((entry.amount, entry.description), (60.0, "ค่าส่งของ"))
        self.assertEqual(entry.on, TODAY - dt.timedelta(days=1))

    def test_a_written_date_baht_and_commas(self):
        entry = self.entry("ค่ากาแฟ 1,250.50 บาท 5/8")
        self.assertEqual((entry.amount, entry.description), (1250.5, "ค่ากาแฟ"))
        self.assertEqual(entry.on, dt.date(2026, 8, 5))

    def test_satang_are_money_not_a_date(self):
        entry = self.entry("ค่ากาแฟ 45.50")
        self.assertEqual((entry.amount, entry.on), (45.5, TODAY))

    def test_thai_month_names(self):
        entry = self.entry("ค่าจอดรถ 40 วันที่ 3 ส.ค.")
        self.assertEqual((entry.amount, entry.description), (40.0, "ค่าจอดรถ"))
        self.assertEqual(entry.on, dt.date(2026, 8, 3))

    def test_two_numbers_are_asked_about(self):
        entry = self.entry("ค่ากระดาษ A4 2 รีม 250")
        self.assertIsNone(entry.amount)
        self.assertIsNone(entry.description)

    def test_no_number_is_not_a_spend(self):
        self.assertIsNone(self.entry("สวัสดีครับ"))

    def test_an_impossible_date_is_asked_not_guessed(self):
        entry = self.entry("ค่าน้ำ 20 31/2")
        self.assertIsNone(entry.on)
        self.assertTrue(entry.date_unclear)


class RuleCorrections(unittest.TestCase):
    def test_labelled_fields(self):
        self.assertEqual(said(correct("จำนวนเงินผิด 120")), {"amount": 120.0})
        self.assertEqual(said(correct("ผู้เบิก Aor")), {"requester": "Aor"})
        self.assertEqual(said(correct("ผู้เบิก aor")), {"requester": "Aor"})
        self.assertEqual(
            said(correct("รายละเอียดเป็นค่าน้ำแข็งใช้ในคลินิก")),
            {"description": "ค่าน้ำแข็งใช้ในคลินิก"},
        )
        self.assertEqual(
            said(correct("วันที่ 3/8 ยอด 85")), {"amount": 85.0, "on": dt.date(2026, 8, 3)}
        )

    def test_a_fund_means_its_last_page(self):
        self.assertEqual(said(correct("ใส่เงินฉุกเฉิน")), {"page": "เงินฉุกเฉิน3"})
        self.assertEqual(said(correct("หน้าเงินสดย่อย5")), {"page": "เงินสดย่อย5"})

    def test_a_page_and_an_amount_together(self):
        self.assertEqual(
            said(correct("ใส่เงินฉุกเฉิน 120")), {"page": "เงินฉุกเฉิน3", "amount": 120.0}
        )

    def test_a_bare_amount_or_date(self):
        self.assertEqual(said(correct("120")), {"amount": 120.0})
        self.assertEqual(said(correct("เมื่อวาน")), {"on": TODAY - dt.timedelta(days=1)})

    def test_a_dash_clears_the_note(self):
        self.assertEqual(said(correct("หมายเหตุ -")), {"note": ""})

    def test_an_unknown_requester_is_dropped(self):
        self.assertTrue(correct("ผู้เบิก Bob").empty)

    def test_chat_is_not_a_correction(self):
        for text in ("ขอบคุณครับ", "โอเค", "ดีมาก"):
            with self.subTest(text=text):
                self.assertTrue(correct(text).empty)


class Applying(unittest.TestCase):
    def test_only_mentioned_fields_change_and_a_blank_note_clears(self):
        draft = Draft("b", "เงินสดย่อย6", TODAY, "ค่าขนม", 23.0, "มน", "เก่า")
        changed = Changes(amount=50.0, note="").apply(draft)
        self.assertEqual(
            (changed.amount, changed.note, changed.description, changed.page),
            (50.0, None, "ค่าขนม", "เงินสดย่อย6"),
        )


class Pages(unittest.TestCase):
    def test_exact_names_win(self):
        self.assertEqual(resolve_page("เงินสดย่อย5", PAGES), "เงินสดย่อย5")
        self.assertEqual(resolve_page("เงินสดย่อย 5", PAGES), "เงินสดย่อย5")

    def test_a_page_that_does_not_exist(self):
        self.assertIsNone(resolve_page("เงินทอน", PAGES))
        self.assertIsNone(resolve_page("เงินฉุกเฉิน", ["เงินสดย่อย6"]))


class FakeOllama:
    def __init__(self, answer=None, fail=False):
        self.answer = answer
        self.fail = fail
        self.payloads: list[dict] = []

    def __call__(self, url, payload, timeout):
        self.payloads.append(payload)
        if self.fail:
            raise OSError("connection refused")
        return {"message": {"content": json.dumps(self.answer, ensure_ascii=False)}}


def blank(**values):
    base = dict(amount=None, date=None, description=None, requester=None, note=None, page=None)
    base.update(values)
    return base


class Model(unittest.TestCase):
    def model(self, answer=None, fail=False):
        post = FakeOllama(answer, fail)
        return OllamaInterpreter("m", post=post), post

    def test_what_the_model_names_is_matched_here(self):
        model, _ = self.model(blank(amount=120, page="ฉุกเฉิน", requester="aor"))
        self.assertEqual(
            said(correct("เงินผิดนะ 120 ใส่ฉุกเฉิน คนเบิกอ้อ aor", model)),
            {"amount": 120.0, "page": "เงินฉุกเฉิน3", "requester": "Aor"},
        )

    def test_anything_not_in_the_message_is_dropped(self):
        """The model once put today's date on every correction."""
        model, _ = self.model(blank(amount=120, date="วันนี้", requester="Aor", page="เงินฉุกเฉิน"))
        self.assertEqual(said(correct("จำนวนเงินผิด 120", model)), {"amount": 120.0})
        model, _ = self.model(blank(amount=99))
        self.assertTrue(correct("จำนวนเงินผิด 120", model).empty)

    def test_an_entry_date_not_in_the_message_is_today(self):
        model, _ = self.model({"amount": 45, "description": "ค่าน้ำแข็ง", "date": "เมื่อวาน"})
        self.assertEqual(model.entry("ค่าน้ำแข็ง 45", TODAY).on, TODAY)

    def test_an_invented_requester_or_page_is_dropped(self):
        model, _ = self.model(blank(requester="Somchai", page="เงินทอน"))
        self.assertTrue(correct("ผู้เบิกสมชาย", model).empty)

    def test_dates_are_read_by_the_rules_not_the_model(self):
        model, _ = self.model(blank(date="เมื่อวาน"))
        self.assertEqual(said(correct("ของเมื่อวาน", model)), {"on": TODAY - dt.timedelta(days=1)})

    def test_a_description_with_an_amount_in_it_is_refused(self):
        model, _ = self.model(blank(description="ค่าน้ำแข็ง 45.00 บาท"))
        self.assertTrue(correct("ค่าน้ำแข็ง", model).empty)

    def test_nonsense_types_are_ignored(self):
        model, _ = self.model(blank(amount="lots", note=5, page=["x"]))
        self.assertTrue(correct("อะไรก็ได้", model).empty)

    def test_the_rules_answer_when_the_model_is_down(self):
        model, post = self.model(fail=True)
        self.assertEqual(said(correct("ผู้เบิก Aor", model)), {"requester": "Aor"})
        self.assertEqual(len(post.payloads), 1)
        self.assertIn("connection refused", model.last_error)
        entry = model.entry("ค่าน้ำแข็ง 45", TODAY)
        self.assertEqual((entry.amount, entry.description), (45.0, "ค่าน้ำแข็ง"))

    def test_the_prompt_carries_the_words_only(self):
        """No Page or Requester names: those are the Workbook's, matched here."""
        model, post = self.model(blank())
        correct("ผู้เบิก Aor", model)
        prompt = json.dumps(post.payloads[0]["messages"], ensure_ascii=False)
        self.assertIn("ผู้เบิก Aor", prompt)
        self.assertNotIn("2026", prompt)
        self.assertNotIn("หมอเก่ง", prompt)
        self.assertNotIn("เงินสดย่อย5", prompt)

    def test_an_entry(self):
        model, _ = self.model({"amount": 80, "description": "ค่าวินมอเตอร์ไซค์ส่งยา", "date": None})
        entry = model.entry("จ่ายวินไปส่งยา 80", TODAY)
        self.assertEqual((entry.amount, entry.description, entry.on), (80.0, "ค่าวินมอเตอร์ไซค์ส่งยา", TODAY))

    def test_an_entry_with_unreadable_date_words_asks(self):
        model, _ = self.model({"amount": 80, "description": "ค่าส่งยา", "date": "วันจันทร์ก่อน"})
        entry = model.entry("ค่าส่งยา 80 วันจันทร์ก่อน", TODAY)
        self.assertTrue(entry.date_unclear)

    def test_not_a_spend(self):
        model, _ = self.model({"amount": None, "description": None, "date": None})
        self.assertIsNone(model.entry("สวัสดีครับ", TODAY))


class Detect(unittest.TestCase):
    def test_rules_without_a_model(self):
        self.assertEqual(detect({}).name, "rules")
        self.assertEqual(detect({"MOUSAI_DESCRIBE_MODEL": "none"}).name, "rules")

    def test_the_description_model_reads_typed_text_too(self):
        self.assertEqual(detect({"MOUSAI_DESCRIBE_MODEL": "sealion"}).name, "ollama:sealion")


if __name__ == "__main__":
    unittest.main()
