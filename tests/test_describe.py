"""The Describer: drafts in, refusals out, and never a stuck receipt."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mousai.describe import (  # noqa: E402
    MAX_LENGTH,
    NullDescriber,
    OllamaDescriber,
    clean,
    detect,
)

RECEIPT = "7-Eleven\nถั่วแระญี่ปุ่น 20.00\nช็อกโกแลต 41.00\nรวม 299.00"


class Ollama:
    """Stands in for Ollama's HTTP API, recording what it was asked."""

    def __init__(self, reply=None, fails=None):
        self.reply = reply
        self.fails = fails
        self.asked = []

    def __call__(self, url, payload, timeout):
        self.asked.append((url, payload, timeout))
        if self.fails:
            raise self.fails
        return self.reply


def answering(description) -> Ollama:
    return Ollama({"message": {"content": json.dumps({"description": description}, ensure_ascii=False)}})


class Drafting(unittest.TestCase):
    def test_a_good_draft_comes_back(self):
        describer = OllamaDescriber("sealion", post=answering("ค่าขนมรับรองลูกค้า"))
        self.assertEqual(describer.describe(RECEIPT, "รับรองลูกค้า"), "ค่าขนมรับรองลูกค้า")

    def test_asks_for_the_schema_deterministically(self):
        fake = answering("ค่าขนมรับรองลูกค้า")
        OllamaDescriber("sealion", base_url="http://mac:11434/", post=fake).describe(RECEIPT, "รับรองลูกค้า")
        url, payload, _ = fake.asked[0]
        self.assertEqual(url, "http://mac:11434/api/chat")
        self.assertEqual(payload["model"], "sealion")
        self.assertEqual(payload["options"]["temperature"], 0)
        self.assertEqual(payload["format"]["required"], ["description"])
        self.assertFalse(payload["stream"])
        self.assertIn("วัตถุประสงค์: รับรองลูกค้า", payload["messages"][-1]["content"])

    def test_without_a_purpose_it_says_so(self):
        fake = answering("ค่าขนม")
        OllamaDescriber("sealion", post=fake).describe(RECEIPT, None)
        self.assertIn("(ไม่ได้บอก)", fake.asked[0][1]["messages"][-1]["content"])

    def test_a_very_long_receipt_is_trimmed(self):
        fake = answering("ค่าขนม")
        OllamaDescriber("sealion", post=fake).describe("ก" * 10_000, "x")
        self.assertLess(len(fake.asked[0][1]["messages"][-1]["content"]), 3_000)


class Refusals(unittest.TestCase):
    def test_down_means_no_draft(self):
        describer = OllamaDescriber("sealion", post=Ollama(fails=ConnectionRefusedError()))
        self.assertIsNone(describer.describe(RECEIPT, "รับรองลูกค้า"))

    def test_an_answer_outside_the_schema_means_no_draft(self):
        for reply in (
            {"message": {"content": "ค่าขนม"}},
            {"message": {"content": "{}"}},
            {"error": "model not found"},
        ):
            with self.subTest(reply=reply):
                describer = OllamaDescriber("sealion", post=Ollama(reply))
                self.assertIsNone(describer.describe(RECEIPT, "x"))

    def test_an_amount_or_a_date_in_the_draft_is_refused(self):
        for draft in ("ค่าขนม 299.00 บาท", "ค่าขนม 14/03", "ค่าขนมใบเสร็จ 16519"):
            with self.subTest(draft=draft):
                self.assertIsNone(clean(draft))

    def test_a_count_is_not_an_amount(self):
        self.assertEqual(clean("ค่าส่งเอกสาร 2 ชุด"), "ค่าส่งเอกสาร 2 ชุด")

    def test_an_essay_is_refused(self):
        self.assertIsNone(clean("ค่า" + "ขนม" * MAX_LENGTH))

    def test_whitespace_and_quotes_are_tidied(self):
        self.assertEqual(clean('  "ค่าขนม   รับรองลูกค้า."  '), "ค่าขนม รับรองลูกค้า")


class Choosing(unittest.TestCase):
    def test_no_model_named_means_the_null_describer(self):
        self.assertIsInstance(detect({}), NullDescriber)
        self.assertIsInstance(detect({"MOUSAI_DESCRIBE_MODEL": "none"}), NullDescriber)
        self.assertIsNone(NullDescriber().describe(RECEIPT, "x"))

    def test_a_named_model_uses_ollama(self):
        describer = detect({"MOUSAI_DESCRIBE_MODEL": "sealion", "MOUSAI_OLLAMA_URL": "http://mac:11434"})
        self.assertIsInstance(describer, OllamaDescriber)
        self.assertEqual(describer.name, "ollama:sealion")


if __name__ == "__main__":
    unittest.main()
