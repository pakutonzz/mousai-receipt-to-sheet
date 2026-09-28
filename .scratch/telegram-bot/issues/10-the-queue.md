# Recorders queue, Keepers decide

Status: ready-for-agent
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
