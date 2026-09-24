"""The web UI: one page to photograph a receipt, check it, and write one Entry.

Everything happens on the home page. A photo is read in the background and what
it says drops into the form; the cells that would be written are recomputed
whenever a field changes, and shown in a review popup that holds the only
button that writes. OCR still never writes anything. It fills in fields that a
person corrects, and nothing is written until they press Confirm in the popup.

What was shown is what gets written. Every preview carries a key derived from
the exact cells it displayed, and Confirm recomputes the Placement from a fresh
read of the Page and refuses unless the key matches. An edit that raced the
preview, a second person writing to the same Page, or a stale cached read can
therefore never turn into cells nobody looked at. It also means Confirm cannot
be pressed at all without a preview having been computed for those exact cells.

The user picks a Page directly rather than a Fund: only they know whether this
spend belongs on เงินสดย่อย6 or on a page someone opened this morning. The Fund
follows from the Page's name, so there is nothing to keep in step.

The Sheets adapter and the OCR reader are injected, so the whole UI is testable
against fakes with no network. Uploaded images are held in memory for the length
of one request and never stored.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import ocr
from .messages import Notice, thai
from .page import Formula, Page, PageError
from .sheets import Sheets, SheetsError, split_ref
from .templates import BY_FUND, fund_for_page

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "views"))

ALLOWED_IMAGES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
MAX_IMAGE_BYTES = 12 * 1024 * 1024

# The sentinel the requester dropdown uses for "a name not in the list".
OTHER = "__other__"

NO_DETAIL = "(no detail)"

# How long one read of a Page serves the live preview. Without it every pause in
# typing is a Sheets read, and the service account has a single per-user quota
# shared by the whole clinic. Confirm always reads fresh, so a stale preview can
# cost the user a second look but never a wrong write.
PREVIEW_TTL = 30.0


def _decimal(raw: str | None) -> float | None:
    if raw is None:
        return None
    cleaned = raw.replace(",", "").strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _date(raw: str | None) -> dt.date | None:
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y"):
        try:
            return dt.datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _entry_date(raw: str | None) -> dt.date | None:
    """Blank means today. Anything else has to be a real date.

    The date field is left blank on purpose rather than pre-filled with today:
    a pre-filled date is indistinguishable from one the user chose, and it used
    to beat the date printed on every receipt.
    """
    if raw is None or not raw.strip():
        return dt.date.today()
    return _date(raw)


def _requester(choice: str, typed: str) -> str:
    """The dropdown wins unless it says 'someone else'."""
    if choice == OTHER:
        return typed.strip() or "-"
    return choice.strip() or "-"


def cells_for_display(placement, template) -> list[dict]:
    """The cells to be written, as a person will see them in the sheet.

    Three of them are stored in a machine form that means nothing to a reader:
    the date is a serial, the balance is a formula, and money carries whatever
    precision float arithmetic left behind. The preview exists to tell someone
    what will be true after they press the button, and "=F28-E29" does not tell
    them the balance. What gets written is unchanged: the balance is still a live
    formula, per ADR 0002.
    """
    date_ref = f"{template.date}{placement.row}"
    money = {
        f"{template.disbursed}{placement.row}",
        f"{template.received}{placement.row}",
    }
    shown = []
    for ref in sorted(placement.cells, key=split_ref):
        value = placement.cells[ref]
        if ref == date_ref:
            text = f"{placement.date:%d/%m/%Y}"
        elif isinstance(value, Formula):
            text = f"{placement.balance:,.2f}"
        elif ref in money and isinstance(value, (int, float)):
            text = f"{value:,.2f}"
        else:
            text = str(value)
        shown.append({"ref": ref, "value": text})
    return shown


# What each column holds, so the review can say "F21 ยอดจ่าย" rather than
# leaving the reader to remember which letter is which on this Fund's layout.
COLUMN_LABELS = {
    "date": "วันที่",
    "sequence": "ลำดับ",
    "description": "รายละเอียด",
    "received": "ยอดรับ",
    "disbursed": "ยอดจ่าย",
    "balance": "คงเหลือ",
    "requester": "ผู้เบิก",
    "note": "หมายเหตุ",
}

# Warnings that mean the money itself looks wrong are shown in red; the rest
# (backdated, a Top-up above, the Page filling up) are worth a look, in amber.
DANGER = {"negative_balance"}


def labelled_cells(placement, template) -> list[dict]:
    """cells_for_display, plus each column's name and the balance's formula.

    The value shown stays the number, per cells_for_display. The formula rides
    alongside so the reader can see the balance is live, not typed in.
    """
    names = {getattr(template, field): label for field, label in COLUMN_LABELS.items()}
    out = []
    for cell in cells_for_display(placement, template):
        written = placement.cells[cell["ref"]]
        out.append(
            {
                **cell,
                "label": names.get(cell["ref"].rstrip("0123456789"), ""),
                "formula": str(written) if isinstance(written, Formula) else None,
            }
        )
    return out


def fingerprint(workbook_id: str, page: str, placement) -> str:
    """A short key for exactly what one preview showed.

    Covers every cell to be written, formulas included, and the balance on
    screen: that moves if someone edits an amount higher up without adding a
    row, which the cells alone would not notice.
    """
    shown = {
        "workbook": workbook_id,
        "page": page,
        "cells": sorted((ref, repr(value)) for ref, value in placement.cells.items()),
        "balance": placement.balance,
    }
    blob = json.dumps(shown, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def group_pages(pages, remembered: dict[str, str]) -> list[dict]:
    """Pages for the picker, grouped by Fund and flagged if remembered."""
    groups: dict[str, dict] = {}
    for name, template in pages:
        group = groups.setdefault(template.fund, {"fund": template.fund, "pages": []})
        group["pages"].append(
            {"name": name, "remembered": remembered.get(template.fund) == name}
        )
    return list(groups.values())


def create_app(sheets: Sheets | None = None, reader=None, clock=time.monotonic) -> FastAPI:
    app = FastAPI(title="mousai")
    state: dict = {"sheets": sheets, "reader": reader, "pages": {}}

    def get_sheets() -> Sheets:
        if state["sheets"] is None:
            state["sheets"] = Sheets.from_env()
        return state["sheets"]

    def get_reader():
        if state["reader"] is None:
            state["reader"] = ocr.detect()
        return state["reader"]

    def cached_page(workbook_id: str, name: str, template) -> Page:
        """A recent read of the Page, for the preview only. Never for writing."""
        now = clock()
        hit = state["pages"].get((workbook_id, name))
        if hit is not None and now - hit[0] < PREVIEW_TTL:
            return hit[1]
        page = get_sheets().open(workbook_id).page(name, template)
        state["pages"][(workbook_id, name)] = (now, page)
        return page

    def forget(workbook_id: str, name: str) -> None:
        state["pages"].pop((workbook_id, name), None)

    def fail(request: Request, notice: Notice, status: int = 400):
        """Errors reach the user in Thai; the English form goes to the log."""
        return TEMPLATES.TemplateResponse(
            request, "error.html", {"message": thai(notice)}, status_code=status
        )

    def refuse(notice: Notice, status: int = 400):
        return JSONResponse({"error": thai(notice)}, status_code=status)

    def survey(workbook):
        """What the pickers need: the Pages, which are remembered, and who spends."""
        pages = workbook.writable_pages()
        remembered = {}
        for fund in BY_FUND:
            try:
                chosen = workbook.active_page(fund)
            except SheetsError:
                chosen = None
            if chosen:
                remembered[fund] = chosen
        return pages, remembered, workbook.requesters()

    @app.get("/health")
    def health():
        return {"ok": True, "ocr": get_reader().name}

    def form_page(
        request: Request,
        *,
        workbook_id: str | None = None,
        message: str | None = None,
        saved: dict | None = None,
        selected_page: str | None = None,
        entry_date: str = "",
        description: str = "",
        amount: str = "",
        requester: str = "-",
        note: str = "",
        status_code: int = 200,
    ):
        """The one page, optionally carrying back what the user already had.

        Reused when Confirm refuses, so a person keeps every field they filled
        in and sees the reason on top, instead of starting over.
        """
        try:
            books = get_sheets().workbooks()
            if not books:
                return fail(request, Notice("no_workbooks"))
            workbook = get_sheets().open(workbook_id or books[0].id)
            pages, remembered, requesters = survey(workbook)
        except SheetsError as error:
            return fail(request, error.notice)
        if not pages:
            return fail(request, Notice("no_pages", {"workbook": workbook.title}))

        names = {name for name, _ in pages}
        default = selected_page if selected_page in names else next(
            (
                p["name"]
                for g in group_pages(pages, remembered)
                for p in g["pages"]
                if p["remembered"]
            ),
            pages[-1][0],
        )
        if requester not in ("", "-") and requester not in requesters:
            requesters = [requester, *requesters]
        return TEMPLATES.TemplateResponse(
            request,
            "index.html",
            {
                "workbooks": books,
                "workbook_id": workbook.id,
                "groups": group_pages(pages, remembered),
                "selected_page": default,
                "requesters": requesters,
                "other": OTHER,
                "ocr_name": get_reader().name,
                "message": message,
                "saved": saved,
                "entry_date": entry_date,
                "description": description,
                "amount": amount,
                "requester": requester,
                "note": note,
            },
            status_code=status_code,
        )

    @app.get("/", response_class=HTMLResponse)
    def index(
        request: Request,
        workbook_id: str | None = None,
        saved_page: str | None = None,
        saved_row: int | None = None,
    ):
        saved = (
            {"page": saved_page, "row": saved_row}
            if saved_page and saved_row
            else None
        )
        return form_page(
            request, workbook_id=workbook_id, saved=saved, selected_page=saved_page
        )

    @app.get("/api/pages")
    def api_pages(workbook_id: str):
        """Repopulate the Page and requester pickers when the Workbook changes."""
        try:
            workbook = get_sheets().open(workbook_id)
            pages, remembered, requesters = survey(workbook)
        except SheetsError as error:
            return refuse(error.notice)
        return {
            "groups": group_pages(pages, remembered),
            "requesters": requesters,
        }

    @app.post("/api/read")
    def api_read(receipt: UploadFile = File(...)):
        """Suggest field values from a photo. Writes nothing and keeps nothing.

        A failed read is not an error: the reader degrades to an empty Reading
        with a note, and the person types the fields instead.
        """
        if receipt.content_type not in ALLOWED_IMAGES:
            return refuse(Notice("not_an_image", {"kind": receipt.content_type or "?"}))
        data = receipt.file.read(MAX_IMAGE_BYTES + 1)
        if len(data) > MAX_IMAGE_BYTES:
            return refuse(
                Notice("image_too_large", {"limit": MAX_IMAGE_BYTES // (1024 * 1024)})
            )
        reading = get_reader().read_image(data, receipt.content_type)
        return {
            "amount": reading.amount,
            "date": reading.date.isoformat() if reading.date else None,
            "description": reading.description or None,
            "notes": [thai(n) for n in reading.notes],
        }

    @app.post("/api/preview")
    def api_preview(
        workbook_id: str = Form(...),
        page: str = Form(...),
        entry_date: str = Form(""),
        description: str = Form(""),
        amount: str = Form(""),
        requester: str = Form("-"),
        requester_other: str = Form(""),
        note: str = Form(""),
    ):
        """What Confirm would write for these fields. Computed, never written.

        Without an amount there are no cells to show yet, but where the Entry
        would go is already known, and so is a Page that is full or broken, so
        those come back straight away.
        """
        template = fund_for_page(page)
        if template is None:
            return refuse(Notice("unknown_page", {"page": page}))
        when = _entry_date(entry_date)
        if when is None:
            return refuse(Notice("bad_date"))
        value = _decimal(amount)
        ready = value is not None and value > 0
        try:
            live = cached_page(workbook_id, page, template)
            placement = live.place(
                on=when,
                description=description.strip() or NO_DETAIL,
                amount=value if ready else 0.0,
                requester=_requester(requester, requester_other),
                note=note.strip() or None,
            )
        except (SheetsError, PageError) as error:
            return refuse(error.notice)

        warnings = [
            {
                "text": thai(w),
                "level": "danger" if w.code in DANGER else "warn",
            }
            for w in placement.warnings
            if ready or w.code != "negative_balance"
        ]
        body = {
            "ready": ready,
            "fund": template.fund,
            "page": page,
            "row": placement.row,
            "sequence": placement.sequence,
            "write_date": placement.write_date,
            "previous_balance": float(live.last_entry.balance),
            # Free rows now, and free rows once this Entry is in.
            "free_rows": live.rows_remaining,
            "rows_remaining": placement.rows_remaining,
            "warnings": warnings,
        }
        if ready:
            body["amount"] = value
            body["balance"] = placement.balance
            body["cells"] = labelled_cells(placement, template)
            body["key"] = fingerprint(workbook_id, page, placement)
        else:
            body["message"] = thai(Notice("amount_to_preview"))
        return body

    @app.post("/confirm", response_class=HTMLResponse)
    def confirm(
        request: Request,
        workbook_id: str = Form(...),
        page: str = Form(...),
        entry_date: str = Form(""),
        description: str = Form(""),
        amount: str = Form(""),
        requester: str = Form("-"),
        requester_other: str = Form(""),
        note: str = Form(""),
        remember: str = Form(""),
        key: str = Form(""),
    ):
        chosen_requester = _requester(requester, requester_other)

        def again(notice: Notice, status: int):
            """Back to the page with every field kept and the reason on top."""
            return form_page(
                request,
                workbook_id=workbook_id,
                message=thai(notice),
                selected_page=page,
                entry_date=entry_date.strip(),
                description=description,
                amount=amount,
                requester=chosen_requester,
                note=note,
                status_code=status,
            )

        template = fund_for_page(page)
        if template is None:
            return fail(request, Notice("unknown_page", {"page": page}))
        value = _decimal(amount)
        when = _entry_date(entry_date)
        if value is None or value <= 0 or when is None:
            return again(Notice("bad_date"), 400)

        try:
            workbook = get_sheets().open(workbook_id)
            # A fresh read, never the preview cache: this is the request that
            # writes, so it works from what the Page says now.
            live = workbook.page(page, template)
            placement = live.place(
                on=when,
                description=description.strip() or NO_DETAIL,
                amount=value,
                requester=chosen_requester,
                note=note.strip() or None,
            )
            if key != fingerprint(workbook_id, page, placement):
                forget(workbook_id, page)
                return again(Notice("preview_stale", {"page": page}), 409)
            workbook.append(live, placement)
            if remember:
                workbook.remember_page(template.fund, page)
        except (SheetsError, PageError) as error:
            forget(workbook_id, page)
            return again(error.notice, 400)

        forget(workbook_id, page)
        # Post/Redirect/Get: reloading the page after a save must not be able
        # to post the same Entry a second time.
        target = urlencode(
            {"workbook_id": workbook_id, "saved_page": page, "saved_row": placement.row}
        )
        return RedirectResponse(url=f"/?{target}", status_code=303)

    return app


app = create_app()
