# A Keeper hands in a receipt and confirms it

Status: resolved
Blocked by: 01, 02, 04, 07, 08

The first complete path: a Keeper's own receipt, no Queue.

## Scope

- Photo → Cloud Vision and `receipt.py` for amount and date → the Describer for
  the Description, asking "ใช้เพื่ออะไร?" with the most common Workbook purposes
  as buttons when there is no caption.
- The Review as one message: Page, row, amount, date, balance before and after,
  warnings, each cell with its column name. Buttons ยืนยันบันทึก · แก้ไข ·
  ยกเลิก.
- แก้ไข: a button per field, the bot asks for the value, the Review is redrawn
  in place. Typed corrections through ticket 05.
- Confirm through the core from ticket 01. A stale Review writes nothing and
  comes back fresh. After 24 hours the buttons refuse.
- Default Page: the Active Page of เงินสดย่อย. Default Requester: the Keeper's
  own.

## Done when

- Tests of the whole path against fakes, including stale, expired and cancelled.
- On the Mac, against the scratch Workbook, a real photo becomes a real row.

## Comments

**2026-09-28, agent.** The code is done and tested against the real Desk and
store with Sheets, Vision and the model faked (`tests/test_bot_review.py`):
captioned photo straight to a Review; no caption asks with purpose buttons or
typed text; no model draft asks for the Description; an unread amount is asked
and checked; แก้ไข offers each field, typed answers redraw the Review in place,
Page and Workbook are picked from buttons; confirm claims first so a double tap
writes once; a stale key redraws a fresh Review and writes nothing; cancel and
the 24-hour expiry refuse the buttons; someone else's buttons do nothing.
A Recorder's Review has no confirm button yet (ticket 10 adds hand-in).
Typed free-form corrections are ticket 05. Left: the live check on the Mac,
a real photo becoming a real row in the scratch Workbook.

**2026-09-29, agent.** Live check done on the Mac: two receipt photos were
confirmed by the Keeper and written to the current Workbook (the store holds two
confirmed Transactions, both with photos, and two recorded photos; the log shows
each confirm's saved message). Resolved.
