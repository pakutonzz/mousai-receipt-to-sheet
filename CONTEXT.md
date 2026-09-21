# mousai

Petty-cash and reimbursement recording for คลินิก มูไซ เวลเนส เซนเตอร์. A person captures a receipt (or declares there was none), checks the extracted figures, and the system records the spend into the clinic's existing cash-disbursement workbook without disturbing the printable forms it is made of.

## Language

### The money

**Fund**:
A pot of clinic cash with its own running balance, replenished in lumps and drawn down by individual spends. Today there are two: เงินสดย่อย (petty cash) and เงินฉุกเฉิน/สำรองจ่าย (emergency/float).
_Avoid_: Category, ประเภท, account, bucket

**Top-up** (ยอดรับ):
Money moved *into* a Fund, raising its balance.
_Avoid_: Deposit, income, credit

**Disbursement** (จำนวนที่เบิก):
Money paid *out of* a Fund for a single spend, lowering its balance.
_Avoid_: Expense, withdrawal, debit

**Balance** (คงเหลือ):
What remains in a Fund after an Entry. Each Entry's balance is derived from the one above it, so Entries in a Page form a chain.

**Requester** (ผู้เบิก):
The person who spent the money and is claiming it back. Who counts as one is not configured anywhere: the names are whoever already appears in the ผู้เบิก column of the Workbook.
_Avoid_: Payer, employee, user

### The workbook

**Workbook**:
One month's spreadsheet, e.g. `เบิกจ่ายเงินสด สิงหาคม26`. It holds that month's Pages for every Fund plus the Ledger sheets, which carry history from earlier months. A new Workbook appears each month and the old one is closed; nothing links them but the opening Balance a person copies across.

**Page** (หน้า):
One detail sheet, e.g. `เงินสดย่อย6`. A Page is one printable, signable form — a document head, a table of Entries, a totals line and a signature block — not a table that grows forever. A Fund's history is a series of Pages, each opening with the closing Balance of the one before.
_Avoid_: Sheet, tab, worksheet (those name the container, not the document)

**Active Page**:
The Page per Fund that an Entry goes to unless someone picks another. It is declared, never inferred: tab order and sheet names do not track it. It is a starting suggestion, not a restriction — any Page in the Workbook can be written to.

**Data region** (พื้นที่รายการ):
The band of rows on a Page that Entries may occupy, bounded above by the column header and below by the totals line. Rows outside it — headings, totals, signatures — are never written to. When it is full, the Page is closed and a new one is opened by hand.

**Entry** (รายการ):
One row inside a Data region: one date, one sequence number, one description, one Top-up or Disbursement, and the resulting Balance.

**Sequence number** (ลำดับ):
An Entry's position *within its date*, not within the Page. It restarts at 1 on each new date, and the date itself is written only on the first Entry of that date.

**Template**:
Which column carries which field on a Page, shared by every Page of one Fund. Funds do not share a Template; เงินสดย่อย starts at column B, เงินฉุกเฉิน at column A. A Template says nothing about where the Data region lies — that varies from Page to Page even within one Fund, and is read off the Page itself.

**Note** (หมายเหตุ):
Free text hung off an Entry, e.g. "รอมนเบิกเพิ่ม 61 บาท". It occupies the column headed ผู้อนุมัติ, which despite its label has never held an approver's name.
_Avoid_: Approver, ผู้อนุมัติ

**Ledger sheet** (ชีทสรุป):
A summary sheet — `ย่อย`, `ฉฉ`, `PT`, `แจกแจง` — recording Top-ups grouped by month. Ledger sheets do not list individual Disbursements.

**Receipt-substitute certificate** (ใบรับรองแทนใบเสร็จ):
A separate signed form declaring spends for which no receipt could be obtained. It has its own Template and its own numbering, and does not carry a Balance.

### The flow

**Transaction**:
One thing the user confirms in the app. Today a Transaction becomes exactly one Entry; it is expected to one day produce several, across more than one sheet.
_Avoid_: Record, submission, receipt
