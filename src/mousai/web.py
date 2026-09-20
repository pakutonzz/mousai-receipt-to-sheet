"""The web UI: photograph a receipt, check what it says, write one Entry.

Three steps, and the middle one is the point of the whole system — OCR never
writes anything. It fills in a form that a person corrects and confirms.

The Sheets adapter and the OCR reader are injected, so the whole UI is testable
against fakes with no network. Uploaded images are held in memory for the length
of one request and never stored.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from fastapi import FastAPI, Form, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from . import ocr
from .messages import Notice, thai
from .page import PageError
from .receipt import Reading
from .sheets import Sheets, SheetsError, load_env
from .templates import BY_FUND

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "views"))

ALLOWED_IMAGES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
MAX_IMAGE_BYTES = 12 * 1024 * 1024


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

    @app.get("/health")
    def health():
        return {"ok": True, "ocr": get_reader().name}

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        try:
            books = get_sheets().workbooks()
        except SheetsError as error:
            return fail(request, error.notice)
        return TEMPLATES.TemplateResponse(
            request,
            "index.html",
            {
                "funds": list(BY_FUND),
                "workbooks": books,
                "ocr_name": get_reader().name,
                "today": dt.date.today().isoformat(),
            },
        )

    @app.post("/preview", response_class=HTMLResponse)
    async def preview(
        request: Request,
        fund: str = Form(...),
        workbook_id: str = Form(...),
        page: str = Form(""),
        entry_date: str = Form(""),
        description: str = Form(""),
        amount: str = Form(""),
        requester: str = Form("-"),
        note: str = Form(""),
        receipt: UploadFile | None = None,
    ):
        if fund not in BY_FUND:
            return fail(request, Notice("unknown_fund", {"fund": fund}))
        template = BY_FUND[fund]

        reading = Reading()
        if receipt is not None and receipt.filename:
            data = await receipt.read()
            if len(data) > MAX_IMAGE_BYTES:
                return fail(request, Notice("image_too_large", {"limit": MAX_IMAGE_BYTES // (1024 * 1024)}))
            if receipt.content_type not in ALLOWED_IMAGES:
                return fail(request, Notice("not_an_image", {"kind": receipt.content_type or "?"}))
            reading = get_reader().read_image(data, receipt.content_type)

        # Anything the user typed wins over anything OCR guessed.
        chosen_amount = _decimal(amount) or reading.amount
        chosen_date = _date(entry_date) or reading.date or dt.date.today()
        chosen_description = description.strip() or reading.description or ""

        try:
            workbook = get_sheets().open(workbook_id)
            target = page or workbook.active_page(fund) or ""
            candidates = workbook.pages_for(template)
            if not target:
                return TEMPLATES.TemplateResponse(
                    request,
                    "choose_page.html",
                    {
                        "fund": fund,
                        "workbook_id": workbook_id,
                        "workbook_title": workbook.title,
                        "candidates": candidates,
                        "entry_date": chosen_date.isoformat(),
                        "description": chosen_description,
                        "amount": chosen_amount or "",
                        "requester": requester,
                        "note": note,
                    },
                )
            if chosen_amount is None or chosen_amount <= 0:
                return fail(request, Notice("amount_required"))

            live = workbook.page(target, template)
            placement = live.place(
                on=chosen_date,
                description=chosen_description or "(no detail)",
                amount=chosen_amount,
                requester=requester.strip() or "-",
                note=note.strip() or None,
            )
        except (SheetsError, PageError) as error:
            return fail(request, error.notice)

        return TEMPLATES.TemplateResponse(
            request,
            "preview.html",
            {
                "fund": fund,
                "workbook_id": workbook_id,
                "workbook_title": workbook.title,
                "page": target,
                "candidates": candidates,
                "placement": placement,
                "warnings": [thai(w) for w in placement.warnings],
                "previous": live.last_entry,
                "entry_date": chosen_date.isoformat(),
                "description": chosen_description,
                "amount": chosen_amount,
                "requester": requester,
                "note": note,
                "reading": reading,
            },
        )

    @app.post("/confirm", response_class=HTMLResponse)
    def confirm(
        request: Request,
        fund: str = Form(...),
        workbook_id: str = Form(...),
        page: str = Form(...),
        entry_date: str = Form(...),
        description: str = Form(...),
        amount: str = Form(...),
        requester: str = Form("-"),
        note: str = Form(""),
        remember: str = Form(""),
    ):
        if fund not in BY_FUND:
            return fail(request, Notice("unknown_fund", {"fund": fund}))
        template = BY_FUND[fund]
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
                requester=requester.strip() or "-",
                note=note.strip() or None,
            )
            workbook.append(live, placement)
            if remember:
                workbook.remember_page(fund, page)
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
