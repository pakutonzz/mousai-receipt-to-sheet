"""Turn a photographed receipt into a Reading, using Google Cloud Vision.

Vision extracts the text; `receipt.py` decides what the numbers mean. That split
is deliberate — the part that can be wrong is pure, offline and testable against
real fixtures, while the part that needs the network does nothing but fetch.

OCR is optional and always has been. With no credentials the app is fully usable
by typing, and *every* failure here — API disabled, quota gone, network down,
blank image — has to come back as an empty Reading with a note. If OCR can take
the manual path down with it, the manual path is not a fallback.

Nothing read here is ever written without a person confirming it.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Protocol

from .messages import Notice, thai
from .receipt import Reading, Word
from .receipt import read as read_text
from .receipt import read_layout
from .sheets import load_env

VISION_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]

# DOCUMENT_TEXT_DETECTION is tuned for dense pages; receipts are sparse columns,
# and TEXT_DETECTION reads them more reliably. Both return the same shape, so
# this is a one-word change if the fixtures ever say otherwise.
FEATURE = "TEXT_DETECTION"
LANGUAGE_HINTS = ["th", "en"]


class ReceiptReader(Protocol):
    name: str

    def read_image(self, data: bytes, mime: str) -> Reading: ...


class NullReader:
    """Always returns nothing. The preview still works; the user types."""

    name = "none"
    configured = False

    def read_image(self, data: bytes, mime: str) -> Reading:
        return Reading(notes=[thai(Notice("ocr_absent"))])


def words_from(response: dict) -> list[Word]:
    """Word boxes out of a Vision response.

    `textAnnotations[0]` is the whole page; every entry after it is one word with
    a bounding polygon. Those boxes are what let the parser pair a label with the
    amount in the far-right column instead of trusting Vision's reading order.
    """
    found = []
    for item in (response.get("textAnnotations") or [])[1:]:
        vertices = (item.get("boundingPoly") or {}).get("vertices") or []
        xs = [v.get("x", 0) for v in vertices]
        ys = [v.get("y", 0) for v in vertices]
        if not xs or not ys:
            continue
        found.append(
            Word(
                text=item.get("description", ""),
                x0=min(xs),
                y0=min(ys),
                x1=max(xs),
                y1=max(ys),
            )
        )
    return found


class GoogleVisionReader:
    name = "google-vision"
    configured = True

    def __init__(self, service):
        self._service = service

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "GoogleVisionReader":
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        env = env if env is not None else load_env()
        credentials = service_account.Credentials.from_service_account_file(
            env.get("GOOGLE_APPLICATION_CREDENTIALS"), scopes=VISION_SCOPES
        )
        return cls(build("vision", "v1", credentials=credentials, cache_discovery=False))

    def read_image(self, data: bytes, mime: str) -> Reading:
        body = {
            "requests": [
                {
                    "image": {"content": base64.b64encode(data).decode()},
                    "features": [{"type": FEATURE}],
                    "imageContext": {"languageHints": LANGUAGE_HINTS},
                }
            ]
        }
        try:
            response = self._service.images().annotate(body=body).execute()
        except Exception as error:  # noqa: BLE001
            # Deliberately broad. A disabled API raises HttpError, a dead network
            # raises OSError, and an expired key raises from the auth library —
            # none of which may reach the user as anything but a note.
            return Reading(notes=[thai(Notice("ocr_unavailable")), _detail(error)])

        result = (response.get("responses") or [{}])[0]
        if "error" in result:
            return Reading(
                notes=[
                    thai(Notice("ocr_unavailable")),
                    str(result["error"].get("message", "")),
                ]
            )

        text = (result.get("fullTextAnnotation") or {}).get("text", "")
        words = words_from(result)
        if not text.strip() and not words:
            return Reading(notes=[thai(Notice("ocr_no_text"))])

        reading = read_layout(words, text=text)
        reading.notes.insert(0, thai(Notice("ocr_read_by_google")))
        return reading


def _detail(error: Exception) -> str:
    """One short line for the person checking, not a stack trace."""
    text = str(error)
    return text[:160] + ("…" if len(text) > 160 else "")


def detect(env: dict[str, str] | None = None) -> ReceiptReader:
    """Pick a backend from what is configured. Never raises: OCR is optional.

    Vision is used whenever the service account key is present. There is no
    enable flag: a project without the Vision API turned on now degrades to a
    note on the preview, so an opt-in switch would only be a way to have receipt
    reading silently off.
    """
    env = env if env is not None else load_env()
    key = env.get("GOOGLE_APPLICATION_CREDENTIALS")
    if key and Path(key).is_file():
        try:
            return GoogleVisionReader.from_env(env)
        except Exception:  # noqa: BLE001 - fall back to typing
            return NullReader()
    return NullReader()
