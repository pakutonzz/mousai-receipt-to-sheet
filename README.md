# mousai

Photograph a receipt, check what it says, and it lands in the right row of the
clinic's cash Workbook in Google Sheets.

The Workbook is a set of printable, signable forms rather than a table — a
document head, a table of entries, a totals line, a signature block. So the hard
part was never reading receipts. It was writing back into a form, across several
different layouts, without breaking it.

- **What the words mean:** [CONTEXT.md](CONTEXT.md)
- **What was agreed and why:** [.scratch/receipt-to-sheet/spec.md](.scratch/receipt-to-sheet/spec.md)
- **The two decisions worth recording:** [docs/adr](docs/adr)

## เริ่มต้นใช้งาน (Quick start)

> ห้าม commit `.env`, ไฟล์ JSON ของ service account ใน `secrets/` หรือ token จริงใด ๆ
> ทั้งสองอย่างอยู่ใน `.gitignore` แล้ว ใช้ `.env.example` เป็นแม่แบบแทน

### 1. วิธีรัน

ใช้ Python 3.11 (ทดสอบกับ 3.11)

```
python -m pip install -r requirements.txt
bash scripts/setup-google-access.sh
python scripts/serve.py
```

ครั้งแรกให้รัน `setup-google-access.sh` ซึ่งจะพาทำทีละขั้น ตั้งแต่สร้าง Google Cloud
project, service account และ key ไปจนถึงแชร์โฟลเดอร์ใน Drive แล้วสร้าง `.env` ให้
ถ้ามีค่าครบอยู่แล้ว ให้ใช้ `cp .env.example .env` แล้วกรอกเองแทนการรัน wizard

### 2. `.env.example`

แม่แบบของทุกค่าที่ใช้ มีคำอธิบายกำกับทุกบรรทัด ค่าที่จำเป็นต้องมี:

| ตัวแปร | ใช้ทำอะไร |
| --- | --- |
| `GOOGLE_APPLICATION_CREDENTIALS` | path ของไฟล์ JSON key ของ service account (เก็บไว้ใน `secrets/`) |
| `MOUSAI_DRIVE_FOLDER_ID` | โฟลเดอร์ Drive ที่เก็บ Workbook รายเดือน แอปหาไฟล์จากที่นี่ |
| `MOUSAI_TEST_SPREADSHEET_ID` | สำเนา Workbook สำหรับทดสอบ อยู่นอกโฟลเดอร์ แอปจะไม่แสดงให้เลือก |

ค่าที่ไม่บังคับ: `MOUSAI_SPREADSHEET_ID` (ใช้กับ `scripts/reconcile.py`),
`MOUSAI_PASSCODE`, `MOUSAI_SESSION_SECRET` และ `GCP_PROJECT_ID` /
`GOOGLE_SERVICE_ACCOUNT_EMAIL` (ใช้ใน wizard)

### 3. `requirements.txt`

รายการ Python package ทั้งหมด ได้แก่ Google API client, FastAPI, uvicorn,
Jinja2 และ python-multipart ส่วน `httpx` ใช้เฉพาะตอนรันเทสต์

### 4. คำสั่ง start app

```
python scripts/serve.py
```

เปิดที่ `http://127.0.0.1:8000` บนเครื่องนี้ และจะพิมพ์ที่อยู่
`http://192.168.x.x:8000` สำหรับโทรศัพท์ที่ต่อ wifi วงเดียวกัน ตัวเลือกเสริม:
`--port 8001`, `--host 127.0.0.1` (เปิดให้เฉพาะเครื่องนี้), `--reload` (ตอนแก้โค้ด)

รันเทสต์: `python -m unittest discover -s tests`

### 5. คำสั่ง start Telegram bot

🚧 **กำลังพัฒนา (in progress)** ยังไม่มีโค้ดของ bot และยังไม่มีคำสั่ง start
ใน `.env.example` เตรียมช่อง `TELEGRAM_BOT_TOKEN` ไว้แล้ว (ตอนนี้ยังไม่มีโค้ดส่วนไหนอ่านค่านี้)

### 6. โครงสร้าง Google Sheet / columns ที่ใช้

- **โฟลเดอร์ Drive** (`MOUSAI_DRIVE_FOLDER_ID`) หนึ่งโฟลเดอร์ เก็บ Workbook เดือนละหนึ่งไฟล์
  ต้องเป็นไฟล์ Google Sheets จริง ไม่ใช่ `.xlsx` ที่อัปโหลดไว้เฉย ๆ และต้องแชร์โฟลเดอร์ให้
  service account เป็น Editor
- **หน้า (sheet) ที่เขียนได้** คือ sheet ที่ชื่อขึ้นต้นด้วย `เงินสดย่อย` หรือ `เงินฉุกเฉิน`
  เช่น `เงินสดย่อย6`, `เงินฉุกเฉิน3` ส่วน sheet อื่น เช่น ทะเบียน `ย่อย` หรือ
  `ใบรับรองแทน…` แอปจะไม่เขียนลงไป
- **ช่วงข้อมูลในแต่ละหน้า** แอปหาเองทุกครั้ง ไม่ได้ตั้งค่าตายตัว เริ่มจากแถวถัดจากหัวตาราง
  (แถวที่มีคำว่า `ว/ด/ป`) ไปจนถึงแถวก่อนแถวที่มีคำว่า `รวมทั้งสิ้น` แถวแรกต้องเป็นยอดยกมา
  ที่มีคงเหลือ แอปจะเขียนลงแถวว่างแถวแรกต่อจากรายการสุดท้าย ไม่ใช้ "แถวสุดท้าย + 1"
  และจะไม่เขียนทับแถวรวมหรือช่องลายเซ็น ถ้าหน้าเต็มจะแจ้งเตือนแทน

| ข้อมูล | หัวคอลัมน์ในชีต | เงินสดย่อย | เงินฉุกเฉิน | สิ่งที่แอปเขียน |
| --- | --- | --- | --- | --- |
| วันที่ | ว/ด/ป | B | A | วันที่ เฉพาะรายการแรกของวันนั้น |
| ลำดับ | ลำดับ | C | B | เริ่ม 1 เมื่อขึ้นวันใหม่ วันเดียวกัน +1 |
| รายละเอียด | รายละเอียด | D | C | ข้อความ |
| ยอดรับ | ยอดรับ | E | D | `-` |
| ยอดจ่าย | จำนวนที่เบิก | F | E | จำนวนเงิน |
| คงเหลือ | คงเหลือ | G | F | สูตร เช่น `=G20-F21` (คงเหลือแถวบน − ยอดจ่าย) |
| ผู้เบิก | ผู้เบิก | H | G | ชื่อ หรือ `-` |
| หมายเหตุ | ผู้อนุมัติ | I | H | ช่องหมายเหตุของแอป เขียนเฉพาะเมื่อกรอก ⚠ |

⚠ หัวคอลัมน์สุดท้ายในชีตจริงคือ **ผู้อนุมัติ** แต่ตอนนี้แอปเขียนช่อง "หมายเหตุ" ลงคอลัมน์นี้
ยังต้องตัดสินใจว่าจะให้เป็นแบบไหน

- **sheet ซ่อนชื่อ `_mousai`** แอปสร้างเองตอนบันทึกครั้งแรกที่เปิดสวิตช์ "จำหน้านี้ไว้"
  มีสองคอลัมน์คือ `fund` และ `active_page` ใช้จำว่าแต่ละกองทุนใช้หน้าไหนอยู่

### 7. Bot ใช้ polling หรือ webhook

🚧 **กำลังพัฒนา (in progress)** ยังไม่ได้ตัดสินใจ ตัว web app ไม่ได้ใช้ทั้งสองแบบ

## Running it

```
python -m pip install -r requirements.txt
bash scripts/setup-google-access.sh    # first time; or cp .env.example .env and fill it in
python scripts/serve.py
```

It prints a `http://192.168.x.x:8000` address to open on a phone on the same
wifi.

### Access

With `MOUSAI_PASSCODE` set in `.env`, every page asks for it once and then
remembers the phone for 12 hours. Without it the app is open to anyone who can
reach it, and `serve.py` says so on startup. That is only fit for a trusted
network. **Never put it behind a tunnel or on the internet without a
passcode**: the app writes to the clinic's cash book, and every receipt read
is billed to the clinic's Cloud Vision account.

- **Revoking access.** Change the passcode and restart the server. A restart
  alone signs everyone out, because sessions are signed with a key made at
  startup (set `MOUSAI_SESSION_SECRET` if you would rather they survived).
- **Wrong passcodes.** Five from one address in ten minutes, or fifty from
  everyone, and logins pause until the window passes.
- **Receipt reading** is capped at 60 an hour and 300 a day, well above what
  one clinic photographs. Past the cap the page asks for the fields by hand.
- **Only the folder's Workbooks** are accepted, whatever `workbook_id` a
  browser sends, and FastAPI's `/docs` console is switched off.

### Reaching it from outside the clinic wifi

Tailscale is the simplest temporary way, because nothing needs installing on
the phones. With the passcode set, and the server on this machine only:

```
python scripts/serve.py --host 127.0.0.1
tailscale funnel --bg 8000
```

`funnel` prints a `https://<machine>.<tailnet>.ts.net` address that any phone
can open. The first time, it may ask for Funnel to be allowed on the tailnet
through a link to the Tailscale admin page. This machine has to stay on and
awake for as long as it is up. Take it down with:

```
tailscale funnel reset
```

For access limited to devices signed in to your tailnet, use `tailscale serve`
instead of `funnel`. Each phone then needs the Tailscale app.

## Setting up from scratch

```
bash scripts/setup-google-access.sh
```

Walks through the Google Cloud project, the service account, the key, and
sharing the Drive folder. Share the **folder**, not a file, so next month's
Workbook inherits access with nobody touching the setup.

Then prove the Workbook is intact before trusting it:

```
python scripts/reconcile.py <spreadsheet-id>
```

## Receipt reading

Optional. The app is fully usable by typing, and it never writes anything OCR
produced without a person confirming it.

Google Cloud Vision extracts the text, then `src/mousai/receipt.py` decides what the
numbers mean — ranked Thai and English total keywords, cash/change/VAT excluded, and
lines rebuilt from word bounding boxes so a label pairs with the amount in the far-right
column. It uses the service account that is already set up for Sheets.

It switches on by itself once the Vision API is enabled on the project (which needs
billing attached, even inside the free 1,000 images a month); there is no flag. If the
API is off, the quota is gone or the network is down, the page shows a note in Thai
and you type the fields. Receipt reading is never load-bearing.

**Measured, not assumed.** `tests/fixtures/receipts/` holds Vision's real output for the
24 images in `sample/`, with the true total for each read off the image by eye in
`expected.json`. The parser gets **22 of 22 amounts** right — every total that is present and legible, and a blank on the two images that have no total — and **21 of 21 dates**, across Buddhist and Christian years, two- and four-digit, slashes, dots, dashes and spelled-out Thai months
— 7-Eleven, Tops, Central, two hospitals, a vet, a school and two invoice templates. Two
are marked known-hard and do not fail the build, both because Vision loses the figure or
its label before any rule could help. Run `python -m unittest discover -s tests` and the
scoreboard prints.

## How it fits together

| | |
| --- | --- |
| `src/mousai/page.py` | The rules. Knows nothing about Google: takes a grid, returns the cells to write. |
| `src/mousai/templates.py` | Which column is which, per Fund. |
| `src/mousai/sheets.py` | The only code that talks to Google. |
| `src/mousai/receipt.py` | Amount, date and description out of receipt text. Pure. |
| `src/mousai/ocr.py` | Google Cloud Vision. Any failure degrades to typing. |
| `src/mousai/messages.py` | Thai for the UI, English for the terminal. The domain emits codes. |
| `src/mousai/web.py` | One page: photo and fields, then a review popup with the cells to be written and the only Confirm. |

Two rules hold the whole thing up, and both are enforced by tests rather than
by intention:

- **The data region is discovered, never configured.** The rows an Entry may
  occupy are found between the `ว/ด/ป` header and the `รวมทั้งสิ้น` totals row,
  because those rows differ per Page even within one Fund — 24, 25, 26, 28 and
  32 rows across the petty-cash Pages alone.
- **A write can only touch values.** Every write is `updateCells` with
  `fields=userEnteredValue`, so it cannot disturb the borders and number formats
  that make the form printable.

## Tests

```
python -m unittest discover -s tests -v
```

Stdlib `unittest`, no network. The Google API and OCR are driven through fakes,
and the domain runs against `tests/fixtures/baseline.json`, a snapshot of the
real Workbook.

**That fixture is not in git.** It contains every cell of the clinic's cash
records, including descriptions naming individuals. Regenerate it locally from
the archived `.xlsx`:

```
python scripts/extract_baseline.py "เบิกจ่ายเงินสด สิงหาคม26.xlsx"
```

The receipt fixtures, by contrast, **are** committed, along with the `sample/` images
they came from — public sample receipts, nothing from the clinic. Re-capture them with
`python scripts/capture_receipts.py` if Vision's output ever changes.

## Scripts

| | |
| --- | --- |
| `setup-google-access.sh` | One-off: project, service account, key, folder share. |
| `extract_baseline.py` | Snapshot the archived `.xlsx` for the tests and reconcile. |
| `reconcile.py` | Diff the live Workbook against that snapshot. Exits non-zero on drift. |
| `format_dates.py` | One-off: set the date columns to `dd/mm/yyyy`. |
| `add_entry.py` | Record an Entry from the terminal. |
| `capture_receipts.py` | One-off: snapshot Vision's output for `sample/` as test fixtures. |
| `serve.py` | Run the web UI. |

## Not built, deliberately

Top-ups and the Ledger sheets, creating a new Page when one fills, writing a
ใบรับรองแทนใบเสร็จ alongside an Entry, and any automatic update of the summary
sheets. A full Page reports an error and asks a person to open the next one.
