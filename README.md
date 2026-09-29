# mousai

Photograph a receipt, check what it says, and it lands in the right row of the
clinic's cash Workbook in Google Sheets, from a web page or a Telegram bot.

The Workbook is a set of printable, signable forms rather than a table: a
document head, a table of entries, a totals line, a signature block. So the hard
part was never reading receipts. It was writing back into a form, across several
different layouts, without breaking it.

- **What the words mean:** [CONTEXT.md](CONTEXT.md)
- **What was agreed and why:** [the web app's spec](.scratch/receipt-to-sheet/spec.md) and [the bot's spec](.scratch/telegram-bot/spec.md)
- **The two decisions worth recording:** [docs/adr](docs/adr)

## วิธีใช้งาน (How to use it)

บันทึกได้สองทาง ผ่าน **Telegram bot** (ทางหลัก ใช้จากโทรศัพท์ได้ทุกที่) หรือผ่าน **หน้าเว็บ**
ทั้งสองทางมีกติกาเดียวกัน: แอปแสดงหน้าตรวจสอบว่าจะเขียนอะไรลงแถวไหน และ
**ไม่มีอะไรถูกเขียนลงชีตจนกว่าจะกดยืนยัน**

### ใครทำอะไรได้

รายชื่ออยู่ในไฟล์ `people.toml` บนเครื่องที่รัน bot (ดูตัวอย่างใน `people.example.toml`)
แก้ไฟล์แล้วมีผลทันทีโดยไม่ต้องรีสตาร์ท

| บทบาท | ใน `people.toml` | ทำอะไรได้ |
| --- | --- | --- |
| ผู้ดูแลสมุด (Keeper) | `keeper` | ส่งใบเสร็จแล้วยืนยันลงสมุดเองได้ ตรวจและยืนยันหรือปฏิเสธรายการในคิว ได้รับแจ้งทุกรายการที่บันทึก |
| ผู้บันทึก (Recorder) | `recorder` | ส่งใบเสร็จ แก้ไข แล้ว **ส่งให้ตรวจ** รายการเข้าคิวรอผู้ดูแลสมุด ได้รับแจ้งผลเมื่อมีคนตรวจ |
| ผู้ดูแลระบบ (operator) | `operator` | ได้รับแจ้งเมื่อมีคนขอใช้งาน และเมื่อระบบขัดข้อง ไม่ได้รับเรื่องบัญชี (ยกเว้นเป็นผู้ดูแลสมุดด้วย) |

คนที่ไม่อยู่ในรายชื่อส่งข้อความหา bot จะได้รับรหัส Telegram ของตัวเองกลับไป ให้ส่งรหัสนั้นให้
ผู้ดูแลระบบเพิ่มลงใน `people.toml` ส่วนผู้ดูแลระบบจะได้รับแจ้งว่ามีคนขอใช้งาน
bot ตอบเฉพาะแชทส่วนตัว ไม่ตอบในกลุ่ม

### ใช้ผ่าน Telegram bot

1. **ส่งรูปใบเสร็จ** ใบเสร็จร้านค้า หรือสลิปโอนเงิน/จ่ายบิล (K PLUS, กรุงไทย, SCB, ttb, เป๋าตัง
   ฯลฯ) ก็ได้ ใส่ข้อความใต้รูปว่า **ใช้เพื่ออะไร** เช่น `รับรองลูกค้า` ถ้าไม่ใส่ bot จะถามพร้อมปุ่ม
   ให้เลือก ระหว่างอ่านจะขึ้น "⏳ กำลังอ่านใบเสร็จ…" (ใช้เวลาราว 5–15 วินาที)
   - ส่งหลายรูปพร้อมกันได้ แต่ละรูปเป็นหนึ่งรายการ และถามว่าใช้เพื่ออะไรครั้งเดียว
   - ถ้ารูปนี้เคยบันทึกไปแล้ว หน้าตรวจสอบจะเตือนว่าอยู่หน้าไหนแถวไหน
2. **หน้าตรวจสอบ** bot อ่านยอดเงินและวันที่ ร่างรายละเอียดด้วยโมเดลบนเครื่อง แล้วแสดง
   ไฟล์ · หน้า · แถว, ยอดจ่าย, วันที่, คงเหลือก่อน → หลัง, คำเตือน (เช่น คงเหลือติดลบ
   หน้าใกล้เต็ม ย้อนวันที่) และเซลล์ที่จะเขียนพร้อมชื่อคอลัมน์
   ถ้าอ่านยอดเงินหรือรายละเอียดไม่ได้ bot จะถามให้พิมพ์
3. **แก้ไข** กดปุ่ม **แก้ไข** แล้วเลือกช่อง (จำนวนเงิน · วันที่ · รายละเอียด · ผู้เบิก ·
   หมายเหตุ · หน้า · ไฟล์) หรือพิมพ์แก้เป็นประโยคได้เลย เช่น
   `จำนวนเงินผิด 120` · `ใส่เงินฉุกเฉิน` · `ผู้เบิก สมศรี` · `ของเมื่อวาน` · `ลบหมายเหตุ`
   ถ้า bot ไม่แน่ใจว่าจะแก้ช่องไหน จะบอกให้ใช้ปุ่มแทน
4. **ยืนยัน** ผู้ดูแลสมุดกด **ยืนยันบันทึก** รายการจึงถูกเขียนลงชีต ผู้บันทึกกด **ส่งให้ตรวจ**
   ทุกคนกด **ยกเลิก** ได้ ถ้าระหว่างนั้นมีคนเขียนลงหน้าเดียวกันก่อน bot จะไม่เขียน แต่ส่ง
   หน้าตรวจสอบใหม่มาให้ยืนยันอีกครั้ง รายการที่ยังไม่ส่งตรวจหรือยืนยัน หมดอายุใน 24 ชั่วโมง
5. **ไม่มีใบเสร็จ** พิมพ์เป็นข้อความ เช่น `ค่าน้ำแข็ง 45` หรือ `ค่าส่งของ 60 เมื่อวาน`
   ช่องหมายเหตุจะได้ **ไม่มีใบเสร็จ** และ bot จะเตือนให้ทำใบรับรองแทนใบเสร็จ

| พิมพ์ / กด | ผล |
| --- | --- |
| รูปใบเสร็จหรือสลิป (+ ข้อความใต้รูป) | เริ่มรายการใหม่ |
| `ค่าน้ำแข็ง 45` (ไม่มีรายการเปิดอยู่) | รายการไม่มีใบเสร็จ |
| `จำนวนเงินผิด 120` (มีรายการเปิดอยู่) | แก้รายการที่เปิดอยู่ |
| `/คิว` | ดูรายการที่รอตรวจ (ผู้บันทึกเห็นเฉพาะของตัวเอง) |
| `/start` | ข้อความต้อนรับตามบทบาท |

**คิว** เมื่อผู้บันทึกส่งให้ตรวจ ผู้ดูแลสมุดทุกคนได้การ์ดพร้อมรูปใบเสร็จ กด **เปิดดู** เพื่อดู
หน้าตรวจสอบที่คำนวณใหม่ ณ ตอนนั้น แก้ไขได้ทุกช่อง แล้ว **ยืนยันบันทึก** หรือ **ปฏิเสธ**
(เลือกเหตุผล ซ้ำ · ไม่ใช่ค่าใช้จ่ายของคลินิก · ข้อมูลไม่ครบ หรือพิมพ์เอง) คนแรกที่กดเป็นคนตัดสิน
การ์ดของคนอื่นจะเปลี่ยนเป็นบอกว่าใครทำอะไร และผู้บันทึกได้รับแจ้งผล รายการในคิวไม่หมดอายุ
และถ้ายังมีค้าง จะมีเตือนวันละครั้งตอน 9 โมง

**หน้าเต็ม** bot ไม่เปิดหน้าใหม่ให้เอง ให้เปิดหน้าใหม่ใน Google Sheets แล้วเลือกหน้าด้วยปุ่ม
**หน้า** ระหว่างนั้นผู้ดูแลสมุดกด **พักไว้ในคิว** ได้ เมื่อบันทึกลงหน้าที่ไม่ใช่หน้าหลักของกองทุน
bot จะถามว่าจะใช้หน้านั้นเป็นหน้าหลักต่อไปหรือไม่

**แจ้งเตือน** ผู้ดูแลสมุดคนอื่นได้รับแจ้งทุกครั้งที่มีการบันทึก (ใคร อะไร เท่าไร หน้าไหนแถวไหน
คงเหลือ) พร้อมเตือนเมื่อหน้าเหลือไม่เกิน 2 แถว คงเหลือติดลบ หรือไม่มีใบเสร็จ
ผู้ดูแลระบบได้รับแจ้งเมื่อการอ่านใบเสร็จ โมเดล Google Sheets หรือตัว bot ขัดข้อง
(ไม่เกินชั่วโมงละครั้งต่อเรื่อง) และเมื่อ bot กลับมาทำงานหลังหยุดไปโดยไม่ได้ตั้งใจ

### ใช้ผ่านหน้าเว็บ

1. เปิดหน้าเว็บ (ถ้ารันบนเครื่องอื่น เปิดผ่าน SSH tunnel ดู "Running it on a Mac mini")
2. เลือกไฟล์และหน้าที่จะบันทึก ค่าเริ่มต้นคือไฟล์ของเดือนปัจจุบันและหน้าหลักของเงินสดย่อย
3. กด **ถ่ายรูป** หรือ **เลือกรูป** แอปอ่านยอดเงิน วันที่ และร่างรายละเอียดให้ ช่องที่มาจาก
   ใบเสร็จจะมีป้าย "จากใบเสร็จ" / "ร่างจากใบเสร็จ" แก้ได้ทุกช่อง และพิมพ์เองทั้งหมดก็ได้
4. **รายละเอียดต้องมีเสมอ** บอกว่าซื้ออะไร เพื่ออะไร เช่น `ค่าขนมปังรับรองลูกค้า`
5. กด **ตรวจสอบก่อนบันทึก** จะขึ้นหน้าต่างแสดงแถวและเซลล์ที่จะเขียน แล้วกด **ยืนยันบันทึก**
   เปิดสวิตช์ "จำหน้านี้ไว้" ถ้าต้องการให้หน้านี้เป็นหน้าหลักของกองทุนต่อจากนี้

### ถ่ายรูปอย่างไรให้อ่านได้

- ให้เห็นบรรทัดยอดรวม/ยอดสุทธิ และวันที่ชัด ๆ ไม่ต้องตรงเป๊ะ รูปเอียงหรือถ่ายแนวนอนก็อ่านได้
- สลิปโอนเงิน ใช้ภาพที่แอปธนาคารบันทึกไว้ได้เลย ไม่ต้องถ่ายหน้าจอซ้ำ
- วันที่ที่ห่างจากวันนี้เกิน 2 ปี แอปจะไม่ใช้ (กันเลขอื่นที่หน้าตาเหมือนวันที่) ให้พิมพ์เอง
- อ่านผิดหรืออ่านไม่ได้ไม่เป็นไร หน้าตรวจสอบมีไว้ให้แก้ก่อนบันทึกเสมอ

## ติดตั้งและรัน (Setup)

> ห้าม commit `.env`, key ของ service account ใน `secrets/`, `people.toml` หรือ token จริงใด ๆ
> ทั้งหมดอยู่ใน `.gitignore` แล้ว ใช้ `.env.example` และ `people.example.toml` เป็นแม่แบบ

ใช้ Python 3.11

```
python -m pip install -r requirements.txt
bash scripts/setup-google-access.sh
```

`setup-google-access.sh` พาทำทีละขั้น ตั้งแต่ Google Cloud project, service account และ key
ไปจนถึงแชร์โฟลเดอร์ใน Drive แล้วสร้าง `.env` ให้ (แชร์ **โฟลเดอร์** ไม่ใช่ไฟล์ Workbook ของเดือน
ถัดไปจะได้สิทธิ์เองโดยไม่ต้องตั้งใหม่) ถ้ามีค่าครบอยู่แล้ว ใช้ `cp .env.example .env` แล้วกรอกเอง
จากนั้นตรวจว่า Workbook ไม่เพี้ยนก่อนเริ่มใช้: `python scripts/reconcile.py <spreadsheet-id>`

### ค่าใน `.env`

`.env.example` มีคำอธิบายกำกับทุกบรรทัด

| ตัวแปร | ใช้ทำอะไร |
| --- | --- |
| `GOOGLE_APPLICATION_CREDENTIALS` | path ของไฟล์ JSON key ของ service account (เก็บไว้ใน `secrets/`) **จำเป็น** |
| `MOUSAI_DRIVE_FOLDER_ID` | โฟลเดอร์ Drive ที่เก็บ Workbook รายเดือน **จำเป็น** |
| `MOUSAI_TEST_SPREADSHEET_ID` | สำเนา Workbook สำหรับทดสอบ อยู่นอกโฟลเดอร์ แอปจะไม่แสดงให้เลือก |
| `TELEGRAM_BOT_TOKEN` | token ของ bot จาก @BotFather จำเป็นสำหรับ bot |
| `MOUSAI_DESCRIBE_MODEL`, `MOUSAI_OLLAMA_URL` | โมเดลใน Ollama ที่ร่างรายละเอียดและอ่านข้อความที่พิมพ์ ถ้าไม่ตั้ง bot จะถามให้พิมพ์และใช้กฎแทน |
| `MOUSAI_PEOPLE_FILE`, `MOUSAI_STORE` | ที่อยู่ของ `people.toml` และฐานข้อมูลคิวของ bot (ค่าเริ่มต้นอยู่ข้างโค้ด) |
| `MOUSAI_PASSCODE`, `MOUSAI_SESSION_SECRET` | รหัสเข้าหน้าเว็บ ดู "Access" |
| `MOUSAI_CLINIC_NAME` | ชื่อคลินิกที่แสดงใต้หัวข้อหน้าเว็บ |

### รันหน้าเว็บ

```
python scripts/serve.py
```

เปิดที่ `http://127.0.0.1:8000` และจะพิมพ์ที่อยู่ `http://192.168.x.x:8000` สำหรับโทรศัพท์ที่ต่อ
wifi วงเดียวกัน ตัวเลือก: `--port 8001`, `--host 127.0.0.1` (เปิดให้เฉพาะเครื่องนี้), `--reload`

### รัน Telegram bot

```
python scripts/bot.py
```

ต้องมี `TELEGRAM_BOT_TOKEN` ใน `.env` และ `people.toml` (คัดลอกจาก `people.example.toml`
แล้วใส่รหัส Telegram ของแต่ละคน) bot ใช้ **long polling** คือไปดึงข้อความจาก Telegram เอง
เครื่องที่รันจึงไม่ต้องเปิดพอร์ตรับการเชื่อมต่อจากภายนอก ข้อความที่ส่งมาตอนเครื่องปิดจะรออยู่ที่
Telegram นานสุด 24 ชั่วโมง

### รันเทสต์

```
python -m unittest discover -s tests
```

## Google Sheet ที่แอปเขียน

- **โฟลเดอร์ Drive** (`MOUSAI_DRIVE_FOLDER_ID`) หนึ่งโฟลเดอร์ เก็บ Workbook เดือนละหนึ่งไฟล์
  ต้องเป็นไฟล์ Google Sheets จริง ไม่ใช่ `.xlsx` ที่อัปโหลดไว้เฉย ๆ และต้องแชร์โฟลเดอร์ให้
  service account เป็น Editor ไฟล์ของเดือนปัจจุบันถูกเลือกจากชื่อเดือนในชื่อไฟล์
- **หน้า (sheet) ที่เขียนได้** คือ sheet ที่ชื่อขึ้นต้นด้วย `เงินสดย่อย` หรือ `เงินฉุกเฉิน`
  เช่น `เงินสดย่อย6`, `เงินฉุกเฉิน3` ส่วน sheet อื่น เช่น ทะเบียน `ย่อย` หรือ
  `ใบรับรองแทน…` แอปจะไม่เขียนลงไป
- **ช่วงข้อมูลในแต่ละหน้า** แอปหาเองทุกครั้ง ไม่ได้ตั้งค่าตายตัว เริ่มจากแถวถัดจากหัวตาราง
  (แถวที่มีคำว่า `ว/ด/ป`) ไปจนถึงแถวก่อนแถวที่มีคำว่า `รวมทั้งสิ้น` แถวแรกต้องเป็นยอดยกมา
  ที่มีคงเหลือ แอปจะเขียนลงแถวว่างแถวแรกต่อจากรายการสุดท้าย และจะไม่เขียนทับแถวรวม
  หรือช่องลายเซ็น ถ้าหน้าเต็มจะแจ้งเตือนแทน

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

**sheet ซ่อนชื่อ `_mousai`** แอปสร้างเองเมื่อมีการตั้งหน้าหลักครั้งแรก มีสองคอลัมน์คือ `fund`
และ `active_page` ใช้จำว่าแต่ละกองทุนใช้หน้าไหนอยู่

## Access

With `MOUSAI_PASSCODE` set, every page asks for it once and then remembers the
phone for 12 hours. Without it the web page is open to anyone who can reach it,
and `serve.py` says so on startup. That only suits a trusted network or a
machine reached through an SSH tunnel. **Never put it behind a public tunnel or
on the internet without a passcode**: it writes to the clinic's cash book, and
every receipt read is billed to the clinic's Cloud Vision account.

- **Revoking access.** Change the passcode and restart. A restart alone signs
  everyone out, unless `MOUSAI_SESSION_SECRET` is set.
- **Wrong passcodes.** Five from one address in ten minutes, or fifty from
  everyone, and logins pause until the window passes.
- **Receipt reading** is capped at 60 an hour and 300 a day. Past the cap the
  page asks for the fields by hand.
- **Only the folder's Workbooks** are accepted, whatever `workbook_id` a browser
  sends, and FastAPI's `/docs` console is switched off.

The bot needs none of this: it answers only the Telegram accounts listed in
`people.toml`, and only in private chats.

## Running it on a Mac mini

The clinic runs both on a Mac mini, as two LaunchAgents: `com.mousai.web` (the
web page, on `127.0.0.1:8000` only) and `com.mousai.bot`. Both start when their
account logs in, restart within ten seconds if they crash, and log to
`~/Library/Logs/mousai/`. The bot's log says who sent what kind of message, how
many replies went out and how long it took, never what the messages said. The
local model runs in Ollama on the same machine.

Nothing on the Mac listens for the outside world. Reach the web page through
SSH, with `<mac>` your SSH host for it and `<clone>` the repo's path there:

```
ssh -N -L 8000:127.0.0.1:8000 <mac>
```

then open `http://127.0.0.1:8000`. To update both and restart them:

```
ssh <mac> 'cd <clone> && git pull --ff-only && launchctl kickstart -k gui/$(id -u)/com.mousai.web && launchctl kickstart -k gui/$(id -u)/com.mousai.bot'
```

- `.env`, the service account key, `people.toml` and
  `tests/fixtures/baseline.json` are copied there by hand over SSH and readable
  only by that account; none of them is in git. The clone pulls with a
  read-only deploy key.
- The bot keeps its Queue in `mousai.db` beside the code. A restart like the
  one above is a clean stop; if the bot stopped any other way (a crash, a
  forced kill, the power), the operators are told when it comes back. Edits to
  `people.toml` take effect without a restart.
- LaunchAgents only start when their account logs in. For the Mac to come back
  by itself after a reboot, it has to log in to that account automatically.

### Reaching it from outside the clinic wifi

Not set up, deliberately. If it ever is, the web page needs `MOUSAI_PASSCODE`
first. Tailscale is the simplest temporary route, since the phones need nothing
installed: with the server on `127.0.0.1`, `tailscale funnel --bg 8000` prints a
public address and `tailscale funnel reset` takes it down; `tailscale serve`
limits it to devices signed in to the tailnet instead.

## Receipt reading

Optional. Everything works by typing, and nothing OCR produced is written
without a person confirming it.

Google Cloud Vision extracts the text, then `src/mousai/receipt.py` decides what
the numbers mean: ranked Thai and English total keywords, cash, change, VAT and
discounts excluded, and lines rebuilt from word bounding boxes so a label pairs
with the amount in the far-right column. It uses the service account already
set up for Sheets and switches on by itself once the Vision API is enabled on
the project. If the API is off, the quota is gone or the network is down, the
person sees a note in Thai and types the fields.

It reads **bank transfer and e-wallet slips** too (K PLUS, Krungthai, SCB, ttb,
เป๋าตัง): the amount sent is on `จำนวนเงิน`, `จำนวนเงินที่ชำระ` or `จำนวน:`, and
the government's co-payment share, fees and negative figures are never taken
for it. **Photos taken sideways**, whose rotation lives only in the EXIF tag,
are turned upright before the lines are rebuilt.

**Measured, not assumed.** `tests/fixtures/receipts/` holds Vision's real output
for the 24 public sample images in `sample/`, with the true total of each read
off the image by eye in `expected.json`. The parser gets **22 of 22 amounts**
(every legible total, and a blank on the two images that have none) and **21 of
21 dates**, across Buddhist and Christian years, two- and four-digit, slashes,
dots, dashes and spelled-out Thai months. The scoreboard prints with the tests.
Real slips and receipts it was also checked against stay on one machine
(`sample/thai-banks/` and `sample/up-to-date/` are gitignored: they carry names
and account numbers); the committed tests imitate their lines instead.

The **Description** is drafted separately by the local model through Ollama
(`src/mousai/describe.py`), from what the receipt says was bought and what the
person said it was for. The model never reads or changes the amount or the
date, and receipt text and people's words stay on the machine that runs it.

## How it fits together

| | |
| --- | --- |
| `src/mousai/page.py` | The rules. Knows nothing about Google: takes a grid, returns the cells to write. |
| `src/mousai/templates.py` | Which column is which, per Fund. |
| `src/mousai/sheets.py` | The only code that talks to Sheets and Drive. Every call retries dropped connections. |
| `src/mousai/receipt.py` | Amount, date and description out of receipt text. Pure. |
| `src/mousai/ocr.py` | Google Cloud Vision. Any failure degrades to typing. |
| `src/mousai/review.py` | The `Desk`: every way in makes a Review and confirms through it, so what was shown is what gets written. |
| `src/mousai/describe.py` | Drafts the Description with the local model. |
| `src/mousai/typed.py` | Reads typed corrections and receipt-less spends: the model says which words are which, rules check them. |
| `src/mousai/people.py` | Who may use the bot, and as what, from `people.toml`. |
| `src/mousai/store.py` | The bot's SQLite store: Transactions in flight, the Queue, photos already recorded. |
| `src/mousai/bot/core.py` | The bot's whole conversation, with no Telegram in it: plain values in, messages to send out. |
| `src/mousai/bot/polling.py` | The only code that imports python-telegram-bot. |
| `src/mousai/web.py` | One page: photo and fields, then a review popup with the cells to be written and the only Confirm. |
| `src/mousai/messages.py` | Thai for people, English for the terminal. The domain emits codes. |

Two rules hold the whole thing up, and both are enforced by tests rather than
by intention:

- **The data region is discovered, never configured.** The rows an Entry may
  occupy are found between the `ว/ด/ป` header and the `รวมทั้งสิ้น` totals row,
  because they differ per Page even within one Fund: 24, 25, 26, 28 and 32 rows
  across the petty-cash Pages alone.
- **A write can only touch values.** Every write is `updateCells` with
  `fields=userEnteredValue`, so it cannot disturb the borders and number formats
  that make the form printable.

## Tests

```
python -m unittest discover -s tests -v
```

Stdlib `unittest`, no network. Google, Vision, the model and Telegram are driven
through fakes, and the domain runs against `tests/fixtures/baseline.json`, a
snapshot of the real Workbook.

**That fixture is not in git.** It contains every cell of the clinic's cash
records, including descriptions naming individuals. Regenerate it locally from
the archived `.xlsx`:

```
python scripts/extract_baseline.py "<the archived workbook>.xlsx"
```

The receipt fixtures, by contrast, **are** committed, with the public sample
images they came from. Re-capture them with `python scripts/capture_receipts.py`
if Vision's output ever changes; it skips any sample git ignores.

## Scripts

| | |
| --- | --- |
| `setup-google-access.sh` | One-off: project, service account, key, folder share. |
| `serve.py` | Run the web page. |
| `bot.py` | Run the Telegram bot. |
| `extract_baseline.py` | Snapshot the archived `.xlsx` for the tests and reconcile. |
| `reconcile.py` | Diff the live Workbook against that snapshot. Exits non-zero on drift. |
| `add_entry.py` | Record an Entry from the terminal. |
| `format_dates.py` | One-off: set the date columns to `dd/mm/yyyy`. |
| `capture_receipts.py` | Snapshot Vision's output for `sample/` as test fixtures. |
| `eval_describer.py` | Measure a local model drafting Descriptions for the sample receipts. |
| `eval_typed.py` | Measure the model reading typed corrections and spends. |

## Not built, deliberately

Top-ups and the Ledger sheets, creating a new Page when one fills, writing a
ใบรับรองแทนใบเสร็จ alongside an Entry (the bot only reminds the Keepers one is
needed), and any automatic update of the summary sheets. A full Page reports
an error and asks a person to open the next one. The model never reads amounts
or dates; those stay with the rules in `receipt.py`.
