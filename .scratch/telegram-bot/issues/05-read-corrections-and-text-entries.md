# Read typed corrections and text-only entries

Status: resolved
Blocked by: 04

Two more jobs for the local model, each with a rule-based fallback.

## Scope

- **Corrections.** A message typed while a Review is open ("จำนวนเงินผิด 120",
  "ใส่เงินฉุกเฉิน", "ผู้เบิก Aor") becomes a set of field changes, which the bot
  shows as an updated Review. Anything the model cannot map to a field is
  answered with "ใช้ปุ่มแก้ไขแทน". The fields are the Review's editable ones, and
  a Page or Requester must be one that exists.
- **Text-only entries.** `ค่าน้ำแข็ง 45`, `ค่าส่งของ 60 เมื่อวาน` become amount,
  Description and date. Without the model: exactly one number means the amount,
  the rest is the Description, and the date is today; otherwise the bot asks.
- Both return proposals only. Nothing is applied without showing a Review.

## Done when

- Tests with the null model cover the rule fallbacks.
- A small set of real-world phrasings, recorded here, is read correctly by the
  chosen model on the Mac.

## Comments

**2026-09-28, agent.** `src/mousai/typed.py`. The model says which words are
which and nothing more: it is shown only the message (no date, no Page or
Requester names), dates come back as the words typed and are read by
`bot/fields.py`, Pages and Requesters are matched against the Workbook here,
and anything it names must appear in the message. That last check was added
after the first run on the Mac, where it put today's date on every correction.

The phrasings are recorded in `tests/fixtures/typed_phrasings.json` (16
corrections, 12 entries; written for this, no clinic records) and run with
`scripts/eval_typed.py`. On the Mac with Gemma-SEA-LION-v4-27B-IT: 28/28, median
3.5 s. The rules alone: 24/28; they ask where there are two numbers
("ค่ากาแฟ 2 แก้ว 110") and miss unlabelled amounts in a sentence ("เงินผิด ต้องเป็น
99.50"), which then get "ใช้ปุ่มแก้ไขแทน".

A correction sends the corrected Review as a new message below the person's,
with what changed on top, and the old one loses its buttons.
