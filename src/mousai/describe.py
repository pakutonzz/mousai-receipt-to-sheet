"""Draft an Entry's Description with a local model.

A Description is "ค่า‹what› ‹why›": what was bought, then what it was for. The
receipt supplies the what; the why is never on it, so it comes from the person
(a caption, or the answer to "ใช้เพื่ออะไร?"). The model's job is to put the
two together the way the Workbook's rows are written.

It runs on the Mac's own Ollama, so the receipt text and the person's words,
which sometimes name a patient, never leave that machine (D06 in the clinic's
agreements).

A draft is only a suggestion that lands in a Review. It is refused, and the
caller asks the person instead, when the model is unavailable, answers
nonsense, runs long, or slips an amount or a date into it: those belong to
the rules in receipt.py, never to the model.
"""

from __future__ import annotations

import json
import re
import urllib.request
from typing import Callable, Protocol

DEFAULT_URL = "http://127.0.0.1:11434"

# Real rows run to a median of 27 characters; allow a long one, refuse an essay.
MAX_LENGTH = 60

# Enough of a receipt to know what was bought. Hospital bills run much longer,
# and every character is prompt the model has to read before it answers.
MAX_RECEIPT_CHARS = 1500

# Reading the prompt is most of the wait (about 100 tokens a second for the
# 27B model on the Mac), and loading the model adds seconds more. So it stays
# loaded all day, and with a context sized for these prompts, which are under
# 2,000 tokens: Ollama's default of 128k tokens took 31 GB for nothing. Every
# caller must ask for the same context, or Ollama reloads the model.
KEEP_ALIVE = "24h"
CONTEXT = 4096

SCHEMA = {
    "type": "object",
    "properties": {"description": {"type": "string"}},
    "required": ["description"],
}

# The examples are written for this prompt in the Workbook's style. The
# Workbook's own rows are not used: they name patients.
INSTRUCTIONS = """\
คุณช่วยเขียนช่อง "รายละเอียด" ในสมุดเบิกจ่ายเงินสดของคลินิก จากข้อความในใบเสร็จและวัตถุประสงค์ที่ผู้ใช้บอก

กติกา:
- ขึ้นต้นด้วย "ค่า" ตามด้วยสิ่งที่ซื้อ สรุปเป็นหมวด ไม่ต้องไล่ทุกรายการ แล้วต่อด้วยวัตถุประสงค์
- ไม่ใช้เครื่องหมายจุลภาค ถ้ามีสองอย่างให้เชื่อมด้วย "และ"
- สั้น ไม่เกินราว 40 ตัวอักษร
- ห้ามใส่จำนวนเงิน วันที่ ชื่อร้าน สาขา หรือเลขที่ใบเสร็จ
- ห้ามเดาสิ่งที่ไม่มีในใบเสร็จ
- ถ้าไม่ได้บอกวัตถุประสงค์ ให้เขียนเฉพาะสิ่งที่ซื้อ

ตัวอย่าง:
ใบเสร็จ: ขนมปังโฮลวีท, นมสด | วัตถุประสงค์: รับรองลูกค้า -> ค่าขนมปังและนมรับรองลูกค้า
ใบเสร็จ: น้ำดื่ม 600 มล. x 12 | วัตถุประสงค์: ใช้ในคลินิก -> ค่าน้ำดื่มใช้ในคลินิก
ใบเสร็จ: EMS ในประเทศ | วัตถุประสงค์: ส่งยาให้คนไข้ -> ค่าส่งยาให้คนไข้ทางไปรษณีย์
ใบเสร็จ: อเมริกาโน่เย็น x 2 | วัตถุประสงค์: รับรองแขก -> ค่ากาแฟรับรองแขก
ใบเสร็จ: กระดาษ A4, ปากกา | วัตถุประสงค์: (ไม่ได้บอก) -> ค่าเครื่องเขียน

ตอบเป็น JSON รูปแบบ {"description": "..."} เท่านั้น"""

# A slipped-in amount or date: a decimal, a long run of digits, or d/m.
FORBIDDEN = re.compile(r"\d+[.,]\d{2}\b|\d{3,}|\d{1,2}[/-]\d{1,2}")


class Describer(Protocol):
    name: str

    def describe(self, receipt_text: str, purpose: str | None) -> str | None: ...


class NullDescriber:
    """No model: every draft is absent, and the bot asks plainly instead."""

    name = "none"

    def describe(self, receipt_text: str, purpose: str | None) -> str | None:
        return None


def clean(draft: str) -> str | None:
    """A usable Description, or None."""
    text = " ".join(draft.split()).strip(" .\"'")
    if not text or len(text) > MAX_LENGTH or FORBIDDEN.search(text):
        return None
    return text


def failure(error: Exception) -> str:
    """One short line naming what went wrong, for the operator."""
    text = f"{type(error).__name__}: {error}"
    return text[:160] + ("…" if len(text) > 160 else "")


def _post_json(url: str, payload: dict, timeout: float) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


class OllamaDescriber:
    """Asks a model served by Ollama, over its local HTTP API."""

    def __init__(
        self,
        model: str,
        base_url: str = DEFAULT_URL,
        timeout: float = 60.0,
        post: Callable[[str, dict, float], dict] = _post_json,
    ):
        self.model = model
        self.name = f"ollama:{model}"
        self._url = base_url.rstrip("/") + "/api/chat"
        self._timeout = timeout
        self._post = post
        # Why the last call failed, for the operator; None after a success.
        self.last_error: str | None = None

    def request(self, receipt_text: str, purpose: str | None) -> dict:
        why = purpose.strip() if purpose and purpose.strip() else "(ไม่ได้บอก)"
        return {
            "model": self.model,
            "stream": False,
            "format": SCHEMA,
            # Deterministic, and short: a Description is a few words, so
            # cap the answer rather than wait out a model that rambles.
            "keep_alive": KEEP_ALIVE,
            "options": {"temperature": 0, "num_predict": 80, "num_ctx": CONTEXT},
            "messages": [
                {"role": "system", "content": INSTRUCTIONS},
                {
                    "role": "user",
                    "content": f"ใบเสร็จ:\n{receipt_text[:MAX_RECEIPT_CHARS]}\n\nวัตถุประสงค์: {why}",
                },
            ],
        }

    def describe(self, receipt_text: str, purpose: str | None) -> str | None:
        try:
            reply = self._post(self._url, self.request(receipt_text, purpose), self._timeout)
            draft = json.loads(reply["message"]["content"])["description"]
        except Exception as error:
            # Down, slow, or answering something that is not the schema: the
            # bot carries on without a draft. Nothing here may stop a receipt.
            self.last_error = failure(error)
            return None
        self.last_error = None
        return clean(str(draft))


def detect(env: dict[str, str]) -> Describer:
    """The Describer the environment asks for; the null one if none is named."""
    model = env.get("MOUSAI_DESCRIBE_MODEL", "").strip()
    if not model or model == "none":
        return NullDescriber()
    return OllamaDescriber(model, env.get("MOUSAI_OLLAMA_URL") or DEFAULT_URL)
