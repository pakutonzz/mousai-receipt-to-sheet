# Recorders queue, Keepers decide

Status: resolved
Blocked by: 09

## Scope

- A Recorder who is not a Keeper sees ส่งให้ตรวจ instead of ยืนยันบันทึก, and
  can still edit before sending.
- The queued Transaction goes to every Keeper. The first to act wins; the
  others' copies are edited to say who confirmed or rejected it.
- A Keeper may change any field and chooses the Page. The Review is worked out
  when the Keeper opens it, never reused from when it was handed in.
- Reject asks for a reason: ซ้ำ · ไม่ใช่ค่าใช้จ่ายของคลินิก · ข้อมูลไม่ครบ, or
  typed. The Recorder hears the outcome either way.
- `/คิว` lists what is waiting. While anything waits, Keepers get one reminder a
  day.
- Queued Transactions never expire.

## Done when

- Tests: two Keepers acting at once, a reject, a Queue item opened after its
  Page moved on.

## Comments

**2026-09-28, agent.** Done; `tests/test_bot_queue.py`. A Recorder's Review has
ส่งให้ตรวจ. Handing in sends every Keeper a card: the receipt photo again (by
its Telegram file id) with the Recorder's name, what and how much, and a
เปิดดู button. Opening works the Review out then, so an item opened after its
Page moved on shows the new row. Confirm claims first, so of two Keepers the
first wins and the second is told who did it; reject offers ซ้ำ ·
ไม่ใช่ค่าใช้จ่ายของคลินิก · ข้อมูลไม่ครบ or a typed reason. Every other card and
Review is edited to say who did what (captions, for photo cards); the Recorder
gets the outcome as a new message. `/คิว` lists what waits, with a button per
item for Keepers. The daily reminder goes to Keepers at the first check after
09:00 while anything waits; the day it last went is kept in memory, so a
restart after nine can repeat it once.
