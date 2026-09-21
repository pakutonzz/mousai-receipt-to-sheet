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
    "amount_needed": "อ่านยอดเงินจากรูปไม่ได้ กรุณากรอกยอดเงินเอง แล้วกดตรวจสอบอีกครั้ง",
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
    "amount_needed": "could not read the amount; type it in and check again",
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
