# Read typed corrections and text-only entries

Status: ready-for-agent
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
