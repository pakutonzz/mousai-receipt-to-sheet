"""Turn a photographed receipt into a Reading.

Three backends, chosen by what is configured:

- **Claude** when `ANTHROPIC_API_KEY` is set. Reads the image directly and
  returns the fields, which handles the messy Thai layouts far better than
  text extraction plus regex.
- **Google Cloud Vision** otherwise, reusing the service account already set up
  for Sheets. Extracts text, then `receipt.py` parses it. Needs the Vision API
  enabled on the project.
- **Nothing**, which is a first-class option: the app is fully usable by typing,
  and the spec requires a manual mode anyway.

No backend is ever trusted. Whatever comes back lands in an editable preview.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Protocol

from .receipt import Reading
from .receipt import read as read_text
from .sheets import load_env

VISION_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-5"

PROMPT = """This is a receipt, most likely Thai.

Return ONLY a JSON object, no prose, with these keys:
  "amount": the total actually paid, as a number. Not the cash tendered, not
            the change, not the VAT, not a subtotal. null if you cannot tell.
  "date": the purchase date as YYYY-MM-DD. Thai receipts often print Buddhist
          years (2569 = 2026). null if absent.
  "description": a short Thai phrase for what was bought, in the style of a
                 petty-cash ledger, e.g. "ค่าขนมปังรับรองลูกค้า" or
                 "ค่ากาแฟคุณหมอ". Keep it under 60 characters.

If the image is not a receipt, return {"amount": null, "date": null,
"description": null}."""


class ReceiptReader(Protocol):
    name: str

    def read_image(self, data: bytes, mime: str) -> Reading: ...


class NullReader:
    """Always returns nothing. The preview still works; the user types."""

    name = "none"
    configured = False

    def read_image(self, data: bytes, mime: str) -> Reading:
        return Reading(notes=["no OCR configured, so fill the fields in by hand"])


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
        key = env.get("GOOGLE_APPLICATION_CREDENTIALS")
        credentials = service_account.Credentials.from_service_account_file(
            key, scopes=VISION_SCOPES
        )
        return cls(build("vision", "v1", credentials=credentials, cache_discovery=False))

    def read_image(self, data: bytes, mime: str) -> Reading:
        response = (
            self._service.images()
            .annotate(
                body={
                    "requests": [
                        {
                            "image": {"content": base64.b64encode(data).decode()},
                            "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
                            "imageContext": {"languageHints": ["th", "en"]},
                        }
                    ]
                }
            )
            .execute()
        )
        result = (response.get("responses") or [{}])[0]
        if "error" in result:
            return Reading(notes=[f"Vision API error: {result['error'].get('message')}"])
        text = (result.get("fullTextAnnotation") or {}).get("text", "")
        if not text.strip():
            return Reading(notes=["Vision found no text in that image"])
        reading = read_text(text)
        reading.notes.insert(0, "read by Google Cloud Vision")
        return reading


def parse_claude_reply(body: dict) -> Reading:
    """Pull a Reading out of the Messages API response. Pure, so it is testable."""
    parts = [
        block.get("text", "")
        for block in body.get("content", [])
        if block.get("type") == "text"
    ]
    text = "\n".join(parts).strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return Reading(text=text, notes=["Claude did not return JSON"])
    try:
        payload = json.loads(match.group())
    except json.JSONDecodeError:
        return Reading(text=text, notes=["Claude returned malformed JSON"])

    amount = payload.get("amount")
    try:
        amount = float(amount) if amount is not None else None
    except (TypeError, ValueError):
        amount = None

    date = None
    raw_date = payload.get("date")
    if isinstance(raw_date, str):
        try:
            date = dt.date.fromisoformat(raw_date.strip())
        except ValueError:
            date = None

    description = payload.get("description")
    if isinstance(description, str):
        description = description.strip()[:60] or None
    else:
        description = None

    return Reading(
        amount=amount,
        date=date,
        description=description,
        text=text,
        notes=["read by Claude; check every field"],
    )


class ClaudeReader:
    name = "claude"
    configured = True

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        post: Callable[[bytes, dict], dict] | None = None,
    ):
        self._key = api_key
        self._model = model
        self._post = post or self._http_post

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "ClaudeReader":
        env = env if env is not None else load_env()
        key = env.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY", "")
        return cls(key, model=env.get("MOUSAI_OCR_MODEL", DEFAULT_MODEL))

    def _http_post(self, payload: bytes, headers: dict) -> dict:
        request = urllib.request.Request(
            ANTHROPIC_URL, data=payload, headers=headers, method="POST"
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read())

    def read_image(self, data: bytes, mime: str) -> Reading:
        body = {
            "model": self._model,
            "max_tokens": 512,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": mime,
                                "data": base64.b64encode(data).decode(),
                            },
                        },
                        {"type": "text", "text": PROMPT},
                    ],
                }
            ],
        }
        headers = {
            "content-type": "application/json",
            "x-api-key": self._key,
            "anthropic-version": ANTHROPIC_VERSION,
        }
        try:
            reply = self._post(json.dumps(body).encode(), headers)
        except urllib.error.HTTPError as error:
            return Reading(notes=[f"Claude API returned {error.code}; fill in by hand"])
        except Exception as error:  # noqa: BLE001 - never block the manual path
            return Reading(notes=[f"could not reach Claude ({error}); fill in by hand"])
        return parse_claude_reply(reply)


def detect(env: dict[str, str] | None = None) -> ReceiptReader:
    """Pick a backend from what is configured. Never raises: OCR is optional."""
    env = env if env is not None else load_env()
    if env.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"):
        return ClaudeReader.from_env(env)
    key = env.get("GOOGLE_APPLICATION_CREDENTIALS")
    if key and Path(key).is_file() and env.get("MOUSAI_ENABLE_VISION", "").lower() in (
        "1",
        "true",
        "yes",
    ):
        try:
            return GoogleVisionReader.from_env(env)
        except Exception:  # noqa: BLE001 - fall back to typing
            return NullReader()
    return NullReader()
