"""The web UI: photograph a receipt, check what it says, write one Entry.

Three steps, and the middle one is the point of the whole system — OCR never
writes anything. It fills in a form that a person corrects and confirms.

The user picks a Page directly rather than a Fund: only they know whether this
spend belongs on เงินสดย่อย6 or on a page someone opened this morning. The Fund
follows from the Page's name, so there is nothing to keep in step.

The Sheets adapter and the OCR reader are injected, so the whole UI is testable
against fakes with no network. Uploaded images are held in memory for the length
of one request and never stored.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from fastapi import FastAPI, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from . import ocr
from .messages import Notice, thai
from .page import Formula, PageError
from .receipt import Reading
from .sheets import Sheets, SheetsError, split_ref
from .templates import BY_FUND, fund_for_page

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "views"))

ALLOWED_IMAGES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
MAX_IMAGE_BYTES = 12 * 1024 * 1024

# The sentinel the requester dropdown uses for "a name not in the list".
OTHER = "__other__"


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


def group_pages(pages, remembered: dict[str, str]) -> list[dict]:
    """Pages for the picker, grouped by Fund and flagged if remembered."""
    groups: dict[str, dict] = {}
    for name, template in pages:
        group = groups.setdefault(template.fund, {"fund": template.fund, "pages": []})
        group["pages"].append(
            {"name": name, "remembered": remembered.get(template.fund) == name}
        )
    return list(groups.values())


def create_app(sheets: Sheets | None = None, reader=None) -> FastAPI:
    app = FastAPI(title="mousai")
    state: dict = {"sheets": sheets, "reader": reader}

    def get_sheets() -> Sheets:
        if state["sheets"] is None:
            state["sheets"] = Sheets.from_env()
        return state["sheets"]

    def get_reader():
        if state["reader"] is None:
            state["reader"] = ocr.detect()
        return state["reader"]

    def fail(request: Request, notice: Notice, status: int = 400):
        """Errors reach the user in Thai; the English form goes to the log."""
        return TEMPLATES.TemplateResponse(
            request, "error.html", {"message": thai(notice)}, status_code=status
        )

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

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        try:
            books = get_sheets().workbooks()
            if not books:
                return fail(request, Notice("no_workbooks"))
            workbook = get_sheets().open(books[0].id)
            pages, remembered, requesters = survey(workbook)
        except SheetsError as error:
            return fail(request, error.notice)
        if not pages:
            return fail(request, Notice("no_pages", {"workbook": workbook.title}))

        default = next(
            (p["name"] for g in group_pages(pages, remembered) for p in g["pages"] if p["remembered"]),
            pages[-1][0],
        )
        return TEMPLATES.TemplateResponse(
            request,
            "index.html",
            {
                "workbooks": books,
                "groups": group_pages(pages, remembered),
                "selected_page": default,
                "requesters": requesters,
                "other": OTHER,
                "ocr_name": get_reader().name,
                "today": dt.date.today().isoformat(),
            },
        )

    @app.get("/api/pages")
    def api_pages(workbook_id: str):
        """Repopulate the Page and requester pickers when the Workbook changes."""
        try:
            workbook = get_sheets().open(workbook_id)
            pages, remembered, requesters = survey(workbook)
        except SheetsError as error:
            return JSONResponse({"error": thai(error.notice)}, status_code=400)
        return {
            "groups": group_pages(pages, remembered),
            "requesters": requesters,
        }

    @app.post("/preview", response_class=HTMLResponse)
    async def preview(
        request: Request,
        workbook_id: str = Form(...),
        page: str = Form(...),
        entry_date: str = Form(""),
        description: str = Form(""),
        amount: str = Form(""),
        requester: str = Form("-"),
        requester_other: str = Form(""),
        note: str = Form(""),
        receipt: UploadFile | None = None,
    ):
        template = fund_for_page(page)
        if template is None:
            return fail(request, Notice("unknown_page", {"page": page}))

        reading = Reading()
        if receipt is not None and receipt.filename:
            data = await receipt.read()
            if len(data) > MAX_IMAGE_BYTES:
                return fail(
                    request,
                    Notice("image_too_large", {"limit": MAX_IMAGE_BYTES // (1024 * 1024)}),
                )
            if receipt.content_type not in ALLOWED_IMAGES:
                return fail(
                    request, Notice("not_an_image", {"kind": receipt.content_type or "?"})
                )
            reading = get_reader().read_image(data, receipt.content_type)

        # Anything the user typed wins over anything OCR guessed.
        chosen_amount = _decimal(amount) or reading.amount
        chosen_date = _date(entry_date) or reading.date or dt.date.today()
        chosen_description = description.strip() or reading.description or ""
        chosen_requester = _requester(requester, requester_other)

        if chosen_amount is None or chosen_amount <= 0:
            return fail(request, Notice("amount_required"))

        try:
            workbook = get_sheets().open(workbook_id)
            pages, remembered, requesters = survey(workbook)
            live = workbook.page(page, template)
            placement = live.place(
                on=chosen_date,
                description=chosen_description or "(no detail)",
                amount=chosen_amount,
                requester=chosen_requester,
                note=note.strip() or None,
            )
        except (SheetsError, PageError) as error:
            return fail(request, error.notice)

        if chosen_requester not in requesters and chosen_requester != "-":
            requesters = [chosen_requester, *requesters]

        return TEMPLATES.TemplateResponse(
            request,
            "preview.html",
            {
                "fund": template.fund,
                "workbook_id": workbook_id,
                "workbook_title": workbook.title,
                "page": page,
                "selected_page": page,
                "groups": group_pages(pages, remembered),
                "requesters": requesters,
                "other": OTHER,
                "placement": placement,
                "cells": cells_for_display(placement, template),
                "warnings": [thai(w) for w in placement.warnings],
                "previous": live.last_entry,
                "entry_date": chosen_date.isoformat(),
                "description": chosen_description,
                "amount": chosen_amount,
                "requester": chosen_requester,
                "note": note,
                "reading": reading,
            },
        )

    @app.post("/confirm", response_class=HTMLResponse)
    def confirm(
        request: Request,
        workbook_id: str = Form(...),
        page: str = Form(...),
        entry_date: str = Form(...),
        description: str = Form(...),
        amount: str = Form(...),
        requester: str = Form("-"),
        requester_other: str = Form(""),
        note: str = Form(""),
        remember: str = Form(""),
    ):
        template = fund_for_page(page)
        if template is None:
            return fail(request, Notice("unknown_page", {"page": page}))
        value = _decimal(amount)
        when = _date(entry_date)
        if value is None or value <= 0 or when is None:
            return fail(request, Notice("bad_date"))

        try:
            workbook = get_sheets().open(workbook_id)
            # Recomputed from the submitted fields, never carried over from the
            # preview: the user may have edited them, and the Page may have moved.
            live = workbook.page(page, template)
            placement = live.place(
                on=when,
                description=description.strip() or "(no detail)",
                amount=value,
                requester=_requester(requester, requester_other),
                note=note.strip() or None,
            )
            workbook.append(live, placement)
            if remember:
                workbook.remember_page(template.fund, page)
        except (SheetsError, PageError) as error:
            return fail(request, error.notice)

        return TEMPLATES.TemplateResponse(
            request,
            "done.html",
            {
                "page": page,
                "placement": placement,
                "workbook_id": workbook_id,
                "workbook_title": workbook.title,
                "remembered": bool(remember),
            },
        )

    return app


app = create_app()
