"""Wording for the things the domain wants to say.

`page.py` emits codes, not sentences: it has no business knowing that the people
using this read Thai and the people running it from a terminal read English.
Both renderings live here, side by side, so adding a case to one and forgetting
the other is obvious.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Notice:
    """Something worth telling the user, which does not stop the Entry."""

    code: str
    values: dict = field(default_factory=dict)

    def __str__(self) -> str:
        return render(self, "en")


TH = {
    "negative_balance": "ยอดคงเหลือจะติดลบ ({balance:,.2f} บาท) บันทึกได้ แต่ควรตรวจสอบ",
    "backdated": "วันที่ {on} ย้อนหลังกว่าแถวบน ({last}) ระบบจะบันทึกต่อท้ายตามปกติ",
    "topup_above": "แถวบนมีรายการรับเงินเข้า ({value}) ระบบยังไม่รองรับ กรุณาตรวจยอดคงเหลือเอง",
    "low_capacity": "หน้านี้เหลือที่ว่างอีก {remaining} แถว ควรเปิดหน้าใหม่เร็ว ๆ นี้",
    "region_full": "หน้า {page} เต็มแล้ว (แถว {first}-{last}) กรุณาเปิดหน้าใหม่ก่อน",
    "no_opening_row": "หน้า {page} ยังไม่มีแถวยกยอดมา กรุณาใส่ยอดยกมาก่อน",
    "no_balance_above": "แถว {row} ของ {page} ไม่มียอดคงเหลือ จึงคำนวณยอดใหม่ไม่ได้",
    "region_not_found": "{page} ไม่มีหัวตาราง {header} หรือแถวรวมทั้งสิ้น อาจไม่ใช่หน้าของ {fund}",
    "row_taken": "แถว {row} ของ {page} ถูกใช้ไปแล้วระหว่างตรวจสอบ ยังไม่มีอะไรถูกบันทึก กรุณาตรวจใหม่",
    "sheet_missing": "ไม่พบชีท {page} ในไฟล์นี้",
    "no_folder": "ยังไม่ได้ตั้งค่าโฟลเดอร์ กรุณาใส่ MOUSAI_DRIVE_FOLDER_ID ใน .env",
    "no_workbooks": "ไม่พบไฟล์ในโฟลเดอร์ ตรวจว่าแชร์โฟลเดอร์ให้ service account แล้วหรือยัง",
    "no_credentials": "ยังไม่ได้ตั้งค่า service account กรุณารัน scripts/setup-google-access.sh",
    "no_page_remembered": "ยังไม่ได้เลือกหน้าสำหรับ {fund} ในไฟล์นี้ เลือกได้จาก: {candidates}",
    "amount_required": "กรุณาใส่จำนวนเงินที่มากกว่าศูนย์",
    "bad_date": "วันที่หรือจำนวนเงินไม่ถูกต้อง",
    "unknown_fund": "ไม่รู้จักประเภทเงิน {fund}",
    "unknown_page": "{page} ไม่ใช่หน้าที่เขียนได้",
    "no_pages": "ไฟล์ {workbook} ไม่มีหน้าที่เขียนได้",
    "image_too_large": "ไฟล์รูปใหญ่เกิน {limit}MB",
    "not_an_image": "อ่านไฟล์ {kind} ไม่ได้ กรุณาใช้รูปภาพ",
    "ocr_absent": "ยังไม่ได้เปิดระบบอ่านใบเสร็จ กรุณากรอกข้อมูลเอง",
    "ocr_unavailable": "อ่านใบเสร็จอัตโนมัติไม่ได้ในขณะนี้ กรุณากรอกข้อมูลเอง",
    "ocr_no_text": "ไม่พบข้อความในรูปนี้ กรุณาถ่ายใหม่ให้ชัดขึ้น หรือกรอกเอง",
    "ocr_read_by_google": "อ่านด้วย Google Cloud Vision กรุณาตรวจสอบทุกช่อง",
    "detail": "{text}",
    "amount_from_keyword": "ยอดเงิน: อ่านจากบรรทัด {keyword}",
    "amount_from_keyword_loose": "ยอดเงิน: อ่านจากบรรทัด {keyword} (ตัวอักษรไม่ชัด)",
    "amount_from_next_line": "ยอดเงิน: อ่านจากบรรทัดถัดจาก {keyword}",
    "amount_from_change": "ยอดเงิน: คำนวณจากเงินสดหักเงินทอน",
    "amount_not_found": "ยอดเงิน: หาไม่พบ กรุณากรอกเอง",
    "date_read": "วันที่: อ่านได้ {text}",
    "date_not_found": "วันที่: หาไม่พบ ใช้วันที่วันนี้",
    "shop_seen": "ร้าน: {shop}",
    "shop_not_found": "ร้าน: หาไม่พบ",
    "amount_to_preview": "กรอกจำนวนเงิน แล้วกดตรวจสอบก่อนบันทึก",
    "login_required": "กรุณาใส่รหัสเข้าใช้งานก่อน",
    "login_wrong": "รหัสไม่ถูกต้อง",
    "login_locked": "ใส่รหัสผิดหลายครั้งเกินไป กรุณารอสักครู่แล้วลองใหม่",
    "unknown_workbook": "ไม่พบไฟล์นี้ในโฟลเดอร์ที่ใช้งาน",
    "ocr_busy": "อ่านใบเสร็จครบจำนวนที่อนุญาตในช่วงนี้แล้ว กรุณากรอกเอง",
    "request_too_large": "ข้อมูลที่ส่งมาใหญ่เกินไป",
    "people_missing": "ไม่พบไฟล์รายชื่อผู้ใช้ {path}",
    "people_unreadable": "อ่านไฟล์รายชื่อผู้ใช้ไม่ได้: {detail}",
    "people_missing_field": "รายชื่อคนที่ {entry} ไม่มีช่อง {field}",
    "people_bad_id": "รายชื่อคนที่ {entry}: telegram_id ต้องเป็นตัวเลขบวก",
    "people_unknown_role": "รายชื่อคนที่ {entry}: ไม่รู้จักบทบาท {role} (ใช้ได้: keeper, recorder, operator)",
    "people_duplicate_id": "telegram_id {id} ซ้ำกัน ในรายชื่อคนที่ {first} และ {second}",
    "people_no_keeper": "ต้องมีผู้ดูแลสมุด (keeper) อย่างน้อยหนึ่งคน",
    "people_no_operator": "ต้องมีผู้ดูแลระบบ (operator) อย่างน้อยหนึ่งคน",
    "txn_missing": "ไม่พบรายการนี้แล้ว",
    "txn_settled": "รายการนี้ดำเนินการไปแล้ว ({state})",
    "bot_not_allowed": "ยังไม่ได้รับอนุญาตให้ใช้งาน รหัสของคุณคือ {id} ส่งรหัสนี้ให้ผู้ดูแลระบบเพื่อขอใช้งาน",
    "bot_access_request": "มีคนขอใช้งาน bot: {who} รหัส {id} ถ้าอนุญาต ให้เพิ่มรหัสนี้ใน people.toml",
    "bot_welcome_keeper": "สวัสดี {name} ส่งรูปใบเสร็จมาได้เลย คุณเป็นผู้ดูแลสมุด ยืนยันรายการลงสมุดได้",
    "bot_welcome_recorder": "สวัสดี {name} ส่งรูปใบเสร็จมาได้เลย รายการจะส่งให้ผู้ดูแลสมุดตรวจก่อนบันทึก",
    "bot_welcome_operator": "สวัสดี {name} คุณจะได้รับแจ้งเมื่อมีคนขอใช้งานหรือระบบขัดข้อง",
    "bot_people_broken": "แก้ไฟล์ people.toml แล้วใช้ไม่ได้ ระบบยังใช้รายชื่อชุดเดิมอยู่: {problem}",
    "bot_help": "ส่งรูปใบเสร็จมาได้เลย ใส่ข้อความใต้รูปว่าใช้เพื่ออะไร เช่น รับรองลูกค้า",
    "bot_review_title": "ตรวจสอบก่อนบันทึก",
    "bot_review_where": "{workbook} · {page} · แถว {row}",
    "bot_review_amount": "ยอดจ่าย ฿{amount}",
    "bot_review_date": "วันที่ {on}",
    "bot_review_balance": "คงเหลือ {before} → {after}",
    "bot_review_same_day": "วันเดียวกับแถวบน ช่องวันที่จะเว้นว่าง",
    "bot_review_cells": "เซลล์ที่จะเขียน",
    "bot_review_formula": "สูตร {formula}",
    "bot_button_confirm": "ยืนยันบันทึก",
    "bot_button_edit": "แก้ไข",
    "bot_button_cancel": "ยกเลิก",
    "bot_button_back": "กลับ",
    "bot_button_type": "พิมพ์เอง",
    "bot_field_amount": "จำนวนเงิน",
    "bot_field_on": "วันที่",
    "bot_field_description": "รายละเอียด",
    "bot_field_requester": "ผู้เบิก",
    "bot_field_page": "หน้า",
    "bot_field_note": "หมายเหตุ",
    "bot_field_workbook": "ไฟล์",
    "bot_ask_purpose": "ใช้เพื่ออะไร? เลือกด้านล่าง หรือพิมพ์มา",
    "bot_ask_purpose_typed": "พิมพ์ว่าใช้เพื่ออะไร เช่น รับรองลูกค้า",
    "bot_purpose_chosen": "ใช้เพื่อ: {purpose}",
    "bot_ask_description": "พิมพ์รายละเอียด เช่น ค่าขนมรับรองลูกค้า",
    "bot_ask_amount": "อ่านยอดเงินจากใบเสร็จไม่ได้ พิมพ์จำนวนเงินมา เช่น 299",
    "bot_ask_new_amount": "พิมพ์จำนวนเงินใหม่ เช่น 299 หรือ 1,250.50",
    "bot_ask_on": "พิมพ์วันที่ เช่น 14/3, 14/03/2569 หรือ เมื่อวาน",
    "bot_ask_requester": "พิมพ์ชื่อผู้เบิก (พิมพ์ - ถ้าไม่มี)",
    "bot_ask_note": "พิมพ์หมายเหตุ (พิมพ์ - เพื่อลบ)",
    "bot_choose_page": "เลือกหน้าที่จะบันทึก",
    "bot_choose_workbook": "เลือกไฟล์",
    "bot_bad_amount": "อ่านจำนวนเงินไม่ได้ พิมพ์เป็นตัวเลข เช่น 299 หรือ 1,250.50",
    "bot_bad_on": "อ่านวันที่ไม่ได้ พิมพ์แบบ 14/3 หรือ 14/03/2569",
    "bot_bad_description": "รายละเอียดว่างหรือยาวเกินไป พิมพ์ใหม่อีกครั้ง",
    "bot_saved": "บันทึกแล้ว: {page} แถว {row} · {description} · ฿{amount} · คงเหลือ {balance}",
    "bot_cancelled": "ยกเลิกรายการนี้แล้ว",
    "bot_failed": "เกิดข้อผิดพลาด ยังไม่ได้บันทึกอะไร ลองส่งใหม่อีกครั้ง",
    "bot_corrected": "แก้ให้แล้ว: {changes}",
    "bot_use_edit_button": "ไม่แน่ใจว่าจะแก้ช่องไหน กดปุ่ม แก้ไข ที่รายการแทน",
    "bot_review_moved": "รายการนี้แก้ไขแล้ว ดูฉบับล่าสุดด้านล่าง",
    "bot_review_no_receipt": "ไม่มีใบเสร็จ ต้องทำใบรับรองแทนใบเสร็จ",
    "bot_saved_no_receipt": "อย่าลืมทำใบรับรองแทนใบเสร็จสำหรับรายการนี้",
    "bot_note_cleared": "ลบหมายเหตุ",
    "bot_expired": "รายการนี้เกิน 24 ชั่วโมงแล้ว ส่งรูปใหม่อีกครั้ง",
    "bot_stale_redrawn": "ระหว่างนั้นหน้านี้มีรายการใหม่ เซลล์ด้านล่างเปลี่ยนแล้ว ตรวจอีกครั้งก่อนยืนยัน",
    "preview_stale": "ข้อมูลในหน้า {page} เปลี่ยนไประหว่างที่ตรวจสอบ (อาจมีคนบันทึกพร้อมกัน) ยังไม่ได้บันทึก กรุณาตรวจสอบเซลล์อีกครั้ง",
}

EN = {
    "negative_balance": "balance would go negative ({balance:,.2f}); saving is still allowed",
    "backdated": "{on} is earlier than the row above ({last}); it will still be appended",
    "topup_above": "the row above records a top-up ({value}); check the balance by hand",
    "low_capacity": "only {remaining} row(s) left on this Page after this Entry",
    "region_full": "{page}: rows {first}-{last} are full; open a new Page first",
    "no_opening_row": "{page}: no opening row; add the ยกยอดมา row first",
    "no_balance_above": "{page}: row {row} has no balance, so a new one cannot be computed",
    "region_not_found": "{page}: no {header} header or totals row; may not be a {fund} Page",
    "row_taken": "{page}: row {row} was taken while you were checking; nothing was written",
    "sheet_missing": "{page} is not a sheet in this Workbook",
    "no_folder": "no folder id; set MOUSAI_DRIVE_FOLDER_ID in .env",
    "no_workbooks": "no spreadsheets in the folder; is it shared with the service account?",
    "no_credentials": "no service account key; run scripts/setup-google-access.sh first",
    "no_page_remembered": "no Page remembered for {fund}; pass --page with one of: {candidates}",
    "amount_required": "an amount is required, and must be more than zero",
    "bad_date": "the date or the amount was not usable",
    "unknown_fund": "unknown fund {fund}",
    "unknown_page": "{page} is not a writable Page",
    "no_pages": "{workbook} has no writable Pages",
    "image_too_large": "that image is larger than {limit}MB",
    "not_an_image": "cannot read {kind}; please use an image",
    "ocr_absent": "no OCR configured, so fill the fields in by hand",
    "ocr_unavailable": "receipt reading is unavailable right now; fill in by hand",
    "ocr_no_text": "no text found in that image; retake it or type the fields",
    "ocr_read_by_google": "read by Google Cloud Vision; check every field",
    "detail": "{text}",
    "amount_from_keyword": "amount: from the {keyword} line",
    "amount_from_keyword_loose": "amount: from the {keyword} line, read loosely",
    "amount_from_next_line": "amount: from the line after {keyword}",
    "amount_from_change": "amount: tendered minus change",
    "amount_not_found": "amount: not found; fill it in by hand",
    "date_read": "date: read {text}",
    "date_not_found": "date: not found; using today",
    "shop_seen": "shop: {shop}",
    "shop_not_found": "shop: not found",
    "amount_to_preview": "type an amount, then review before saving",
    "login_required": "enter the passcode first",
    "login_wrong": "wrong passcode",
    "login_locked": "too many wrong passcodes; wait a few minutes and try again",
    "unknown_workbook": "that spreadsheet is not in the Workbook folder",
    "ocr_busy": "the receipt-reading limit for now has been reached; type the fields",
    "request_too_large": "the request is too large",
    "people_missing": "no people file at {path}",
    "people_unreadable": "cannot read the people file: {detail}",
    "people_missing_field": "person {entry} has no {field}",
    "people_bad_id": "person {entry}: telegram_id must be a positive number",
    "people_unknown_role": "person {entry}: unknown role {role} (use keeper, recorder, operator)",
    "people_duplicate_id": "telegram_id {id} appears twice, for persons {first} and {second}",
    "people_no_keeper": "at least one person must be a keeper",
    "people_no_operator": "at least one person must be an operator",
    "txn_missing": "that Transaction no longer exists",
    "txn_settled": "that Transaction is already {state}",
    "bot_not_allowed": "not allowed yet; your ID is {id}. Send it to the operator to ask for access",
    "bot_access_request": "access request: {who}, ID {id}. To allow it, add the ID to people.toml",
    "bot_welcome_keeper": "hello {name}. Send a receipt photo; as a Keeper you can confirm Entries",
    "bot_welcome_recorder": "hello {name}. Send a receipt photo; a Keeper checks it before it is recorded",
    "bot_welcome_operator": "hello {name}. You will hear about access requests and system failures",
    "bot_people_broken": "the edit to people.toml did not take; the previous list is still in force: {problem}",
    "bot_help": "send a receipt photo, with a caption saying what it was for",
    "bot_review_title": "review before saving",
    "bot_review_where": "{workbook} · {page} · row {row}",
    "bot_review_amount": "paid ฿{amount}",
    "bot_review_date": "dated {on}",
    "bot_review_balance": "balance {before} → {after}",
    "bot_review_same_day": "same day as the row above; the date cell stays blank",
    "bot_review_cells": "cells to be written",
    "bot_review_formula": "formula {formula}",
    "bot_button_confirm": "confirm",
    "bot_button_edit": "edit",
    "bot_button_cancel": "cancel",
    "bot_button_back": "back",
    "bot_button_type": "type it",
    "bot_field_amount": "amount",
    "bot_field_on": "date",
    "bot_field_description": "description",
    "bot_field_requester": "requester",
    "bot_field_page": "page",
    "bot_field_note": "note",
    "bot_field_workbook": "workbook",
    "bot_ask_purpose": "what was it for? pick one below or type it",
    "bot_ask_purpose_typed": "type what it was for, e.g. hosting a client",
    "bot_purpose_chosen": "for: {purpose}",
    "bot_ask_description": "type the description, e.g. ค่าขนมรับรองลูกค้า",
    "bot_ask_amount": "the receipt's total could not be read; type the amount, e.g. 299",
    "bot_ask_new_amount": "type the new amount, e.g. 299 or 1,250.50",
    "bot_ask_on": "type the date, e.g. 14/3, 14/03/2569 or yesterday",
    "bot_ask_requester": "type the requester's name (- for none)",
    "bot_ask_note": "type the note (- to clear it)",
    "bot_choose_page": "choose the Page",
    "bot_choose_workbook": "choose the Workbook",
    "bot_bad_amount": "that is not an amount; type a number such as 299 or 1,250.50",
    "bot_bad_on": "that is not a date; type it like 14/3 or 14/03/2569",
    "bot_bad_description": "the description is empty or too long; type it again",
    "bot_saved": "saved: {page} row {row} · {description} · ฿{amount} · balance {balance}",
    "bot_cancelled": "cancelled",
    "bot_failed": "something went wrong; nothing was saved. Try sending it again",
    "bot_corrected": "changed: {changes}",
    "bot_use_edit_button": "not sure which field to change; use the edit button on the Review",
    "bot_review_moved": "changed; the latest version is below",
    "bot_review_no_receipt": "no receipt: a receipt-substitute certificate is needed",
    "bot_saved_no_receipt": "remember the receipt-substitute certificate for this one",
    "bot_note_cleared": "note removed",
    "bot_expired": "this is more than 24 hours old; send the photo again",
    "bot_stale_redrawn": "the Page gained an Entry meanwhile; the cells below changed, check them before confirming",
    "preview_stale": "{page} changed while it was being checked (someone else may have written to it); nothing was written, check the cells again",
}


# Codes whose whole body is a value supplied at runtime (an API error string,
# say). They have no wording of their own, in either language.
PASSTHROUGH = {"detail"}


def render(notice: Notice, language: str = "th") -> str:
    table = TH if language == "th" else EN
    pattern = table.get(notice.code)
    if pattern is None:
        return f"{notice.code} {notice.values}"
    try:
        return pattern.format(**notice.values)
    except (KeyError, ValueError, IndexError):
        return f"{notice.code} {notice.values}"


def thai(notice: Notice) -> str:
    return render(notice, "th")


def english(notice: Notice) -> str:
    return render(notice, "en")
