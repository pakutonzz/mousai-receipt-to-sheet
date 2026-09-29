"""The web UI: one page to photograph a receipt, check it, and write one Entry.

Everything happens on the home page. A photo is read in the background and what
it says drops into the form; the cells that would be written are recomputed
whenever a field changes, and shown in a review popup that holds the only
button that writes. OCR still never writes anything. It fills in fields that a
person corrects, and nothing is written until they press Confirm in the popup.

What was shown is what gets written. Every preview carries a key derived from
the exact cells it displayed, and Confirm refuses unless a fresh read gives the
same key, so Confirm cannot be pressed at all without a preview of those exact
cells. That rule lives in review.py, which the bot shares; this module parses
forms, calls it, and renders.

The user picks a Page directly rather than a Fund: only they know whether this
spend belongs on เงินสดย่อย6 or on a page someone opened this morning. The Fund
follows from the Page's name, so there is nothing to keep in step.

The Sheets adapter and the OCR reader are injected, so the whole UI is testable
against fakes with no network. Uploaded images are held in memory for the length
of one request and never stored.
"""

from __future__ import annotations

import datetime as dt
import os
import time
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import describe, ocr
from .access import SESSION_COOKIE, Limiter, Sessions, passcode_matches
from .messages import Notice, thai
from .page import PageError
from .review import PREVIEW_TTL, Desk, Draft, Stale, severity  # noqa: F401  PREVIEW_TTL: tests read it from here
from .sheets import Sheets, SheetsError, load_env
from .templates import BY_FUND, fund_for_page

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "views"))

ALLOWED_IMAGES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
MAX_IMAGE_BYTES = 12 * 1024 * 1024

# The sentinel the requester dropdown uses for "a name not in the list".
OTHER = "__other__"

# Every receipt read is a Cloud Vision call on the clinic's billing account.
# Far above what one clinic photographs, far below a runaway bill.
READS_PER_HOUR = 60
READS_PER_DAY = 300

# Wrong passcodes: per client, and across everyone, in any ten minutes.
TRIES_PER_CLIENT = 5
TRIES_OVERALL = 50
TRIES_WINDOW = 600.0

# Anything bigger is refused before the body is parsed or spooled to disk.
MAX_BODY_BYTES = MAX_IMAGE_BYTES + 1024 * 1024

# Paths that work without a session.
OPEN_PATHS = {"/login", "/health"}

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    # The Confirm button must never be clickable inside someone else's frame.
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "frame-ancestors 'none'",
    "Referrer-Policy": "same-origin",
    # Balances and names; no shared cache should keep them.
    "Cache-Control": "no-store",
}


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


def group_pages(pages, remembered: dict[str, str]) -> list[dict]:
    """Pages for the picker, grouped by Fund and flagged if remembered."""
    groups: dict[str, dict] = {}
    for name, template in pages:
        group = groups.setdefault(template.fund, {"fund": template.fund, "pages": []})
        group["pages"].append(
            {"name": name, "remembered": remembered.get(template.fund) == name}
        )
    return list(groups.values())


def client_of(request: Request) -> str:
    """Who is asking, for counting wrong passcodes.

    Behind a tunnel every connection comes from localhost. Uvicorn already
    swaps in the X-Forwarded-For address, but only for connections from this
    machine, so a device on the Wi-Fi cannot forge its way around the limit
    by sending the header itself. Wrong passcodes are capped across everyone
    as well, in case the tunnel's address is all there is.
    """
    return request.client.host if request.client else "?"


def create_app(
    sheets: Sheets | None = None,
    reader=None,
    clock=time.monotonic,
    *,
    passcode: str | None = None,
    session_secret: bytes | None = None,
    wall=time.time,
    read_limits: tuple[int, int] = (READS_PER_HOUR, READS_PER_DAY),
    describer=None,
    clinic_name: str = "",
) -> FastAPI:
    """The app. With a passcode, everything but /login and /health needs a
    session. Without one it is open, which only suits a trusted local network.
    """
    # No interactive API console: it would be a second, unguarded front door
    # to everything the page does.
    app = FastAPI(title="mousai", docs_url=None, redoc_url=None, openapi_url=None)
    # Shown under the page title. From the machine's .env, so the code names no clinic.
    TEMPLATES.env.globals["clinic_name"] = clinic_name
    state: dict = {"sheets": sheets, "reader": reader, "describer": describer}
    sessions = Sessions(session_secret or os.urandom(32), wall=wall)
    tries_by_client = Limiter(TRIES_PER_CLIENT, TRIES_WINDOW, clock)
    tries_overall = Limiter(TRIES_OVERALL, TRIES_WINDOW, clock)
    reads_hourly = Limiter(read_limits[0], 3600.0, clock)
    reads_daily = Limiter(read_limits[1], 86400.0, clock)

    def signed_in(request: Request) -> bool:
        return not passcode or sessions.valid(request.cookies.get(SESSION_COOKIE))

    @app.middleware("http")
    async def guard(request: Request, call_next):
        length = request.headers.get("content-length", "")
        if length.isdigit() and int(length) > MAX_BODY_BYTES:
            response = JSONResponse(
                {"error": thai(Notice("request_too_large"))}, status_code=413
            )
        elif request.url.path in OPEN_PATHS or signed_in(request):
            response = await call_next(request)
        elif request.url.path.startswith("/api/"):
            response = JSONResponse(
                {"error": thai(Notice("login_required"))}, status_code=401
            )
        else:
            response = RedirectResponse("/login", status_code=303)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    def get_sheets() -> Sheets:
        if state["sheets"] is None:
            state["sheets"] = Sheets.from_env()
        return state["sheets"]

    desk = Desk(get_sheets, clock)

    def get_reader():
        if state["reader"] is None:
            state["reader"] = ocr.detect()
        return state["reader"]

    def get_describer():
        if state["describer"] is None:
            state["describer"] = describe.detect(load_env())
        return state["describer"]

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

    def login_page(request: Request, notice: Notice | None = None, status: int = 200):
        return TEMPLATES.TemplateResponse(
            request,
            "login.html",
            {"message": thai(notice) if notice else None},
            status_code=status,
        )

    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request):
        if signed_in(request):
            return RedirectResponse("/", status_code=303)
        return login_page(request)

    @app.post("/login", response_class=HTMLResponse)
    def login(request: Request, code: str = Form("")):
        if not passcode:
            return RedirectResponse("/", status_code=303)
        who = client_of(request)
        # Checked before the passcode, so a locked-out guesser learns nothing
        # even when the guess happens to be right.
        if tries_by_client.blocked(who) or tries_overall.blocked():
            return login_page(request, Notice("login_locked"), 429)
        if not passcode_matches(code.strip(), passcode):
            tries_by_client.hit(who)
            tries_overall.hit()
            return login_page(request, Notice("login_wrong"), 401)
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            SESSION_COOKIE,
            sessions.issue(),
            max_age=sessions.seconds,
            httponly=True,
            # Lax, not Strict: a link opened from a chat app is a cross-site
            # navigation, and Strict would ask for the passcode every time.
            # Lax still withholds the cookie from cross-site POSTs.
            samesite="lax",
            secure=request.url.scheme == "https"
            or request.headers.get("x-forwarded-proto") == "https",
            path="/",
        )
        return response

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
            found = desk.workbooks()
            if not found:
                return fail(request, Notice("no_workbooks"))
            if workbook_id:
                desk.check_workbook(workbook_id)
            workbook = get_sheets().open(workbook_id or found[0].id)
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
                "workbooks": found,
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
            desk.check_workbook(workbook_id)
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
        if reads_hourly.blocked() or reads_daily.blocked():
            return refuse(Notice("ocr_busy"), 429)
        reads_hourly.hit()
        reads_daily.hit()
        reading = get_reader().read_image(data, receipt.content_type)
        # The same local model the bot uses drafts รายละเอียด from what the
        # receipt says was bought. Nobody said why here, so the draft names
        # only the what; the person adds the why before saving.
        drafted = get_describer().describe(reading.text, None) if reading.text else None
        return {
            "amount": reading.amount,
            "date": reading.date.isoformat() if reading.date else None,
            "description": drafted,
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
        if fund_for_page(page) is None:
            return refuse(Notice("unknown_page", {"page": page}))
        when = _entry_date(entry_date)
        if when is None:
            return refuse(Notice("bad_date"))
        draft = Draft(
            workbook_id=workbook_id,
            page=page,
            on=when,
            description=description,
            amount=_decimal(amount),
            requester=_requester(requester, requester_other),
            note=note,
        )
        try:
            review = desk.review(draft)
        except (SheetsError, PageError) as error:
            return refuse(error.notice)

        body = {
            "ready": review.ready,
            "fund": review.fund,
            "page": page,
            "row": review.row,
            "sequence": review.sequence,
            "write_date": review.write_date,
            "previous_balance": review.previous_balance,
            # Free rows now, and free rows once this Entry is in.
            "free_rows": review.free_rows,
            "rows_remaining": review.rows_remaining,
            "warnings": [
                {"text": thai(w), "level": severity(w)} for w in review.warnings
            ],
        }
        if review.ready:
            body["amount"] = draft.amount
            body["balance"] = review.balance
            body["cells"] = list(review.cells)
            body["key"] = review.key
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
        if not description.strip():
            return again(Notice("description_required"), 400)

        draft = Draft(
            workbook_id=workbook_id,
            page=page,
            on=when,
            description=description,
            amount=value,
            requester=chosen_requester,
            note=note,
        )
        try:
            placement = desk.confirm(draft, key, remember=bool(remember))
        except Stale as stale:
            return again(stale.notice, 409)
        except (SheetsError, PageError) as error:
            return again(error.notice, 400)

        # Post/Redirect/Get: reloading the page after a save must not be able
        # to post the same Entry a second time.
        target = urlencode(
            {"workbook_id": workbook_id, "saved_page": page, "saved_row": placement.row}
        )
        return RedirectResponse(url=f"/?{target}", status_code=303)

    return app


def settings_from_env() -> dict:
    """MOUSAI_PASSCODE turns the door on. MOUSAI_SESSION_SECRET, if set, keeps
    people signed in across restarts; unset, a restart signs everyone out."""
    env = load_env()
    secret = env.get("MOUSAI_SESSION_SECRET")
    return {
        "passcode": env.get("MOUSAI_PASSCODE") or None,
        "session_secret": secret.encode("utf-8") if secret else None,
        "clinic_name": (env.get("MOUSAI_CLINIC_NAME") or "").strip(),
    }


app = create_app(**settings_from_env())
