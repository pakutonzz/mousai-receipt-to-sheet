# A Keeper hands in a receipt and confirms it

Status: ready-for-agent
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
