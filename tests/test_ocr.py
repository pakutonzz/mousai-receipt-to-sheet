"""Offline tests for the OCR backends.

No network: Claude is driven through an injected `post`, Vision through a fake
service. What matters here is that a backend can never break the manual path —
every failure has to degrade into an empty Reading with a note, not an exception.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import unittest
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mousai.ocr import (  # noqa: E402
    ClaudeReader,
    GoogleVisionReader,
    NullReader,
    detect,
    parse_claude_reply,
)

IMAGE = b"\xff\xd8\xff\xe0 not really a jpeg"


def claude_saying(text: str):
    return {"content": [{"type": "text", "text": text}]}


class ClaudeReplies(unittest.TestCase):
    def test_clean_json(self):
        reading = parse_claude_reply(
            claude_saying(
                '{"amount": 23, "date": "2026-08-03", '
                '"description": "ค่าขนมปังรับรองลูกค้า"}'
            )
        )
        self.assertEqual(reading.amount, 23.0)
        self.assertEqual(reading.date, dt.date(2026, 8, 3))
        self.assertEqual(reading.description, "ค่าขนมปังรับรองลูกค้า")

    def test_json_wrapped_in_chatter(self):
        reading = parse_claude_reply(
            claude_saying('Here you go:\n```json\n{"amount": 65.5}\n```\nHope that helps')
        )
        self.assertEqual(reading.amount, 65.5)

    def test_nulls_are_fine(self):
        reading = parse_claude_reply(
            claude_saying('{"amount": null, "date": null, "description": null}')
        )
        self.assertTrue(reading.empty)

    def test_a_bad_date_does_not_poison_the_amount(self):
        reading = parse_claude_reply(
            claude_saying('{"amount": 12, "date": "not a date"}')
        )
        self.assertEqual(reading.amount, 12.0)
        self.assertIsNone(reading.date)

    def test_over_long_description_is_trimmed(self):
        reading = parse_claude_reply(claude_saying(json.dumps({"description": "ก" * 200})))
        self.assertEqual(len(reading.description), 60)

    def test_no_json_at_all(self):
        reading = parse_claude_reply(claude_saying("I cannot read this image"))
        self.assertTrue(reading.empty)
        self.assertIn("did not return JSON", reading.notes[0])

    def test_malformed_json(self):
        reading = parse_claude_reply(claude_saying('{"amount": }'))
        self.assertTrue(reading.empty)
        self.assertIn("malformed", reading.notes[0])


class ClaudeTransport(unittest.TestCase):
    def test_sends_the_image_and_the_model(self):
        captured = {}

        def post(payload, headers):
            captured["body"] = json.loads(payload)
            captured["headers"] = headers
            return claude_saying('{"amount": 23}')

        reader = ClaudeReader("test-key", model="claude-sonnet-5", post=post)
        reading = reader.read_image(IMAGE, "image/jpeg")

        self.assertEqual(reading.amount, 23.0)
        self.assertEqual(captured["body"]["model"], "claude-sonnet-5")
        self.assertEqual(captured["headers"]["x-api-key"], "test-key")
        content = captured["body"]["messages"][0]["content"]
        self.assertEqual(content[0]["type"], "image")
        self.assertEqual(content[0]["source"]["media_type"], "image/jpeg")

    def test_an_http_error_degrades_to_typing(self):
        def post(payload, headers):
            raise urllib.error.HTTPError(
                "url", 401, "Unauthorized", hdrs=None, fp=None
            )

        reading = ClaudeReader("bad-key", post=post).read_image(IMAGE, "image/jpeg")
        self.assertTrue(reading.empty)
        self.assertIn("401", reading.notes[0])

    def test_a_dead_network_degrades_to_typing(self):
        def post(payload, headers):
            raise OSError("no route to host")

        reading = ClaudeReader("key", post=post).read_image(IMAGE, "image/jpeg")
        self.assertTrue(reading.empty)
        self.assertIn("could not reach", reading.notes[0])


class FakeVision:
    def __init__(self, response):
        self._response = response

    def images(self):
        return self

    def annotate(self, body=None):
        self.body = body
        return self

    def execute(self):
        return self._response


class Vision(unittest.TestCase):
    def test_parses_extracted_text(self):
        service = FakeVision(
            {
                "responses": [
                    {"fullTextAnnotation": {"text": "ร้านกาแฟ\nรวม 65.00\n03/08/2026"}}
                ]
            }
        )
        reading = GoogleVisionReader(service).read_image(IMAGE, "image/jpeg")
        self.assertEqual(reading.amount, 65.00)
        self.assertIn("Google Cloud Vision", reading.notes[0])

    def test_api_error_degrades_to_typing(self):
        service = FakeVision({"responses": [{"error": {"message": "API not enabled"}}]})
        reading = GoogleVisionReader(service).read_image(IMAGE, "image/jpeg")
        self.assertTrue(reading.empty)
        self.assertIn("API not enabled", reading.notes[0])

    def test_blank_image(self):
        service = FakeVision({"responses": [{}]})
        reading = GoogleVisionReader(service).read_image(IMAGE, "image/jpeg")
        self.assertTrue(reading.empty)
        self.assertIn("no text", reading.notes[0])


class Selection(unittest.TestCase):
    def test_no_configuration_means_no_ocr_not_a_crash(self):
        reader = detect({})
        self.assertIsInstance(reader, NullReader)
        reading = reader.read_image(IMAGE, "image/jpeg")
        self.assertTrue(reading.empty)
        self.assertIn("by hand", reading.notes[0])

    def test_an_anthropic_key_selects_claude(self):
        reader = detect({"ANTHROPIC_API_KEY": "sk-test"})
        self.assertIsInstance(reader, ClaudeReader)

    def test_vision_is_opt_in(self):
        """A Sheets key alone must not imply the Vision API is enabled."""
        reader = detect({"GOOGLE_APPLICATION_CREDENTIALS": "secrets/x.json"})
        self.assertIsInstance(reader, NullReader)


if __name__ == "__main__":
    unittest.main()
