# Spec: Telegram bot

Hand in a receipt from a phone chat; a Keeper checks it and it lands in the
right row of the Workbook, exactly as the web page does today.

Words are the glossary's: [CONTEXT.md](../../CONTEXT.md). Recorder, Keeper,
Queue, Review, Description and Transaction are defined there, and this spec
uses them in that sense only. The web app's rules still hold, and the bot adds
none of its own for placing an Entry: [receipt-to-sheet/spec.md](../receipt-to-sheet/spec.md),
[ADR 0001](../../docs/adr/0001-google-sheets-as-system-of-record.md),
[ADR 0002](../../docs/adr/0002-write-cells-with-explicit-types.md).

Earlier agreements with the clinic are in the handoff pack of 16 Sep 2026
(D01–D11). This spec follows D05 (others queue for the Keeper), D06 (outside AI
may read receipt photos, not patient data), D08 (the Keeper picks the Page) and
D09 (a full Page holds items; no Page is ever opened automatically). D02/D04
(Excel on the office PC) are superseded once the bookkeeper moves to the Google Sheet.

## Who

- **Recorders** hand in receipts. Each has a Telegram account, a name, and a
  default Requester, listed by hand in a config file. Anyone not on the list who
  messages the bot is told their Telegram ID and to ask the operator, and the
  operator is told they asked. Nothing else happens.
- **Keepers** (the bookkeeper and the clinic's owner to start) may confirm. A Keeper is also
  a Recorder: their own receipts skip the Queue.
- **The operator** (the person running the system) receives access requests and
  system failures, not book matters.
- Private chats only. The bot does not join groups.

## Handing in a receipt

1. A photo, with an optional caption, sent to the bot. Each photo of an album is
   its own Transaction.
2. Amount and date come from Cloud Vision and the existing rules in
   `receipt.py`, unchanged. The LLM never reads or changes them.
3. The Description is drafted by a local LLM from the receipt's *what* and the
   caption's *why*. With no caption, the bot asks "ใช้เพื่ออะไร?" and offers the
   most common purposes found in the Workbook as buttons. A Description is
   required.
4. The bot replies with a Review in the same shape as the web popup: Page, row,
   amount, date, balance before and after, warnings, and each cell with its
   column name.
5. **แก้ไข** offers one button per field (จำนวนเงิน · วันที่ · รายละเอียด ·
   ผู้เบิก · หน้า · หมายเหตุ · ไฟล์). Typed corrections also work and are read by
   the LLM. Either way the Review message is redrawn in place.
6. A Recorder who is not a Keeper taps **ส่งให้ตรวจ**, and the Transaction goes to
   the Queue. A Keeper taps **ยืนยันบันทึก**. Both can tap **ยกเลิก**.

A text message such as `ค่าน้ำแข็ง 45` is a Transaction with no receipt: the LLM
reads the amount, what and when; without the LLM, one number is the amount and
the rest is the Description. Its Note gets **ไม่มีใบเสร็จ**, and Keepers are told
it needs a receipt-substitute certificate.

## The Queue

- A queued Transaction is sent to **every** Keeper with its Review and buttons.
  The first Keeper to act wins; the others' copies are edited to say who did
  what. `/คิว` lists what is waiting.
- A Keeper may change any field and chooses the Page (D08), then confirms or
  **rejects with a reason** (quick buttons: ซ้ำ · ไม่ใช่ค่าใช้จ่ายของคลินิก ·
  ข้อมูลไม่ครบ, or free text). The Recorder is told the outcome either way.
- Queued Transactions never expire. The Review is worked out **when a Keeper
  opens it**, so a day-old item can never write day-old cells.
- While anything waits, Keepers get one reminder a day.
- A full Page holds the Transaction in the Queue (D09); the Keeper can choose
  another Page.

## Writing

Exactly the web page's rules: what the Review showed is what gets written.
Confirming recomputes the Placement from a fresh read and refuses if the cells
differ, answering with a fresh Review to confirm instead. A Keeper's own direct
Review cannot be confirmed after 24 hours.

- **Page:** the Active Page of เงินสดย่อย by default. Choosing another Page
  offers to make it the Active Page for everyone, like the web page's switch.
- **Workbook:** always the current month's, by the month in its name, never by
  last-modified time. A late receipt keeps its true date and carries the
  backdated warning; the previous month's Workbook is closed.
- **Same photo twice:** the Review warns and names the earlier Entry, for
  example *รูปนี้บันทึกไปแล้ว: เงินสดย่อย6 แถว 21 · ค่าขนมรับรองลูกค้า*. It can
  still be confirmed.

## Notifications

- **Keepers:** every saved Entry (who, what, amount, Page, row, balance); a Page
  with two or fewer free rows; a negative Balance; each no-receipt spend.
- **Operator:** access requests; failures of OCR, the LLM, Sheets or the bot.

## The LLM

Local, on the Mac mini's Ollama. Nothing but the receipt photo leaves the
machine, and that only to Cloud Vision (D06). The model is chosen by
measurement: SEA-LION v4 27B, Aya Expanse 8B and Qwen 2.5 7B drafting
Descriptions for real receipts, judged against how the Workbook's rows are
written, within about five seconds. Use the upstream `aisingapore/…` model, not
a teammate's custom build.

It does three jobs: draft the Description, read typed corrections, read
text-only entries. It sits behind one interface, like the OCR reader, and when
it is unavailable the bot carries on with plain questions and the field
buttons. Nothing waits on it.

## Where it runs

The Mac mini runs the bot, the web page and the LLM, as services that start at
boot.

- The bot uses long polling: nothing on the Mac is reachable from outside.
  Messages sent while it is off wait at Telegram for up to 24 hours.
- The web page listens on 127.0.0.1 only and is reached through an SSH tunnel.
  It knows nobody, so it confirms directly and bypasses the Queue: until
  deployment is decided it is the team's tool, not the clinic's.
- Code is written elsewhere and pulled onto the Mac with a read-only deploy key.
- The Queue and the same-photo index are a local database on the Mac. Losing it
  loses unconfirmed items, which Recorders can resend from their chat history.
  Nothing unconfirmed ever goes into the Workbook.
- Receipt photos are not archived beyond the chats themselves.

## Out of scope

- Top-ups (ยอดรับ) through the bot.
- Writing the receipt-substitute certificate itself.
- Any deployment reachable from the internet, and a login for the web page.
- Moving the real book: a change of `MOUSAI_DRIVE_FOLDER_ID` and a share with
  the service account when she is ready.

## Build order

The tickets in [issues/](issues/) are numbered in the order they unblock each
other. The web page's own changes (current Workbook by name, drafted
Description, no more `(no detail)`) ride along where they share code.
