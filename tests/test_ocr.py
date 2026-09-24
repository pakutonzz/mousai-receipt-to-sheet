"""Offline tests for the Vision backend.

No network: the Vision client is a fake. What matters here is not that OCR works
— that is what the receipt fixtures are for — but that it can never take the
manual path down with it. Every failure has to arrive as an empty Reading with a
note, never as an exception reaching the web layer.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mousai import ocr  # noqa: E402
from mousai.ocr import GoogleVisionReader, NullReader, detect, words_from  # noqa: E402

IMAGE = b"\xff\xd8\xff\xe0 not really a jpeg"


class HttpErrorLike(Exception):
    """Stands in for googleapiclient.errors.HttpError without the dependency."""


def annotation(text: str, x0: int, y0: int, x1: int, y1: int) -> dict:
    return {
        "description": text,
        "boundingPoly": {
            "vertices": [
                {"x": x0, "y": y0},
                {"x": x1, "y": y0},
                {"x": x1, "y": y1},
                {"x": x0, "y": y1},
            ]
        },
    }


class FakeVision:
    """Returns a canned response, or raises, depending on how it was built."""

    def __init__(self, response=None, raises: Exception | None = None):
        self._response = response
        self._raises = raises
        self.body = None

    def images(self):
        return self

    def annotate(self, body=None):
        self.body = body
        return self

    def execute(self):
        if self._raises is not None:
            raise self._raises
        return self._response


def reader_raising(error: Exception) -> GoogleVisionReader:
    return GoogleVisionReader(FakeVision(raises=error))


def reader_returning(response: dict) -> GoogleVisionReader:
    return GoogleVisionReader(FakeVision(response=response))


class NeverBreaksTheManualPath(unittest.TestCase):
    """The bug this suite previously missed: a 403 arrives as a raised error."""

    def test_a_disabled_api_degrades_to_typing(self):
        reading = reader_raising(
            HttpErrorLike("Cloud Vision API has not been used in project 123456789012")
        ).read_image(IMAGE, "image/jpeg")
        self.assertTrue(reading.empty)
        self.assertEqual(reading.notes[0].code, "ocr_unavailable")

    def test_a_blown_quota_degrades_to_typing(self):
        reading = reader_raising(HttpErrorLike("429 Quota exceeded")).read_image(
            IMAGE, "image/jpeg"
        )
        self.assertTrue(reading.empty)
        self.assertIn("429", " ".join(str(n) for n in reading.notes))

    def test_a_dead_network_degrades_to_typing(self):
        reading = reader_raising(OSError("no route to host")).read_image(
            IMAGE, "image/jpeg"
        )
        self.assertTrue(reading.empty)

    def test_an_error_inside_the_response_degrades_to_typing(self):
        reading = reader_returning(
            {"responses": [{"error": {"message": "API not enabled"}}]}
        ).read_image(IMAGE, "image/jpeg")
        self.assertTrue(reading.empty)
        self.assertIn("API not enabled", " ".join(str(n) for n in reading.notes))

    def test_a_blank_image_says_so_in_thai(self):
        reading = reader_returning({"responses": [{}]}).read_image(IMAGE, "image/jpeg")
        self.assertTrue(reading.empty)
        self.assertEqual(reading.notes[0].code, "ocr_no_text")

    def test_the_detail_line_is_trimmed_not_a_stack_trace(self):
        reading = reader_raising(HttpErrorLike("x" * 500)).read_image(IMAGE, "image/jpeg")
        self.assertLessEqual(max(len(str(n)) for n in reading.notes), 200)


class WordBoxes(unittest.TestCase):
    def test_skips_the_full_page_entry(self):
        response = {
            "textAnnotations": [
                {"description": "everything\non the page"},
                annotation("รวม", 10, 100, 60, 120),
            ]
        }
        words = words_from(response)
        self.assertEqual([w.text for w in words], ["รวม"])

    def test_reads_the_box(self):
        word = words_from({"textAnnotations": [{}, annotation("111.00", 300, 100, 380, 120)]})[0]
        self.assertEqual((word.x0, word.y0, word.x1, word.y1), (300, 100, 380, 120))
        self.assertEqual(word.middle, 110)

    def test_an_entry_with_no_polygon_is_skipped_not_fatal(self):
        words = words_from({"textAnnotations": [{}, {"description": "orphan"}]})
        self.assertEqual(words, [])

    def test_no_annotations_at_all(self):
        self.assertEqual(words_from({}), [])


class ReadingAReceipt(unittest.TestCase):
    def test_pairs_a_label_with_its_far_right_column_amount(self):
        """The 7-Eleven layout: label on the left, amount way off to the right."""
        response = {
            "responses": [
                {
                    # Vision's own text ordering separates the two.
                    "fullTextAnnotation": {"text": "ยอดสุทธิ\nอื่น ๆ\n100.00"},
                    "textAnnotations": [
                        {"description": "ignored"},
                        annotation("ยอดสุทธิ", 20, 500, 120, 522),
                        annotation("100.00", 600, 502, 700, 520),
                        annotation("เงินทอน", 20, 560, 120, 582),
                        annotation("0.00", 620, 562, 700, 580),
                    ],
                }
            ]
        }
        reading = reader_returning(response).read_image(IMAGE, "image/jpeg")
        self.assertEqual(reading.amount, 100.00)

    def test_says_who_read_it(self):
        response = {
            "responses": [
                {
                    "fullTextAnnotation": {"text": "ร้านกาแฟ\nรวม 65.00"},
                    "textAnnotations": [
                        {"description": "x"},
                        annotation("รวม", 10, 10, 50, 30),
                        annotation("65.00", 200, 10, 260, 30),
                    ],
                }
            ]
        }
        reading = reader_returning(response).read_image(IMAGE, "image/jpeg")
        self.assertEqual(reading.amount, 65.00)
        self.assertEqual(reading.notes[0].code, "ocr_read_by_google")


class Selection(unittest.TestCase):
    def test_no_credentials_means_no_ocr_not_a_crash(self):
        reader = detect({})
        self.assertIsInstance(reader, NullReader)
        reading = reader.read_image(IMAGE, "image/jpeg")
        self.assertTrue(reading.empty)
        self.assertEqual(reading.notes[0].code, "ocr_absent")

    def test_a_missing_key_file_means_no_ocr(self):
        reader = detect({"GOOGLE_APPLICATION_CREDENTIALS": "secrets/not-there.json"})
        self.assertIsInstance(reader, NullReader)

    def test_a_present_key_selects_vision(self):
        sentinel = object()
        original = GoogleVisionReader.from_env
        GoogleVisionReader.from_env = classmethod(lambda cls, env=None: sentinel)
        try:
            chosen = detect({"GOOGLE_APPLICATION_CREDENTIALS": str(ROOT / "README.md")})
        finally:
            GoogleVisionReader.from_env = original
        self.assertIs(chosen, sentinel)

    def test_a_broken_client_falls_back_rather_than_raising(self):
        original = GoogleVisionReader.from_env

        def explode(cls, env=None):
            raise RuntimeError("malformed key file")

        GoogleVisionReader.from_env = classmethod(explode)
        try:
            chosen = detect({"GOOGLE_APPLICATION_CREDENTIALS": str(ROOT / "README.md")})
        finally:
            GoogleVisionReader.from_env = original
        self.assertIsInstance(chosen, NullReader)

    def test_there_is_no_enable_flag_left(self):
        """Vision is the tool; a flag would only be a way to have it silently off."""
        self.assertNotIn("MOUSAI_ENABLE_VISION", Path(ocr.__file__).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
