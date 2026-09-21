"""The Google Sheets and Drive adapter.

Everything that talks to Google lives here and nothing else does, so the rules
in `page.py` stay testable offline. The one piece of real logic in this file,
turning a Placement into API requests, is a pure function so it can be tested
without credentials too.

Writes go through `updateCells` with `fields="userEnteredValue"`, which cannot
touch cell formatting: that is what lets an Entry drop into a pre-formatted
empty row without painting borders. See
docs/adr/0002-write-cells-with-explicit-types.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .messages import Notice, english
from .page import Formula, Page, PageError, column_index
from .templates import Template, fund_for_page

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
]

SPREADSHEET_MIME = "application/vnd.google-apps.spreadsheet"

# Hidden, so it never prints and never shows in the sheet tab strip.
CONFIG_SHEET = "_mousai"
CONFIG_HEADER = ["fund", "active_page"]


class SheetsError(Exception):
    """Carries a Notice so the UI can say it in Thai. See messages.py."""

    def __init__(self, notice: Notice):
        self.notice = notice
        super().__init__(english(notice))


class RowTaken(SheetsError):
    """Someone filled the target row between reading it and writing to it."""


class SheetNotFound(SheetsError):
    pass


@dataclass(frozen=True)
class WorkbookRef:
    """A Workbook as the picker shows it."""

    id: str
    title: str
    modified: str


# -- pure: Placement -> API requests ---------------------------------------


def cell_value(value) -> dict:
    """Map a Python value to a Sheets `ExtendedValue`, by type, never by content."""
    if isinstance(value, Formula):
        return {"formulaValue": value.text}
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, (int, float)):
        return {"numberValue": float(value)}
    return {"stringValue": str(value)}


def split_ref(ref: str) -> tuple[int, int]:
    """'D21' -> (21, 4), both 1-based."""
    match = re.fullmatch(r"([A-Z]+)(\d+)", ref)
    if not match:
        raise ValueError(f"bad cell ref: {ref}")
    letters, row = match.groups()
    return int(row), column_index(letters)


def build_update_requests(sheet_id: int, cells: dict[str, object]) -> list[dict]:
    """One `updateCells` request per cell.

    Per-cell rather than one range, because a Placement skips the date column on
    a same-day Entry and a contiguous write would have to send something for the
    gap, clearing a cell we were never asked to touch.
    """
    requests = []
    for ref in sorted(cells, key=split_ref):
        row, col = split_ref(ref)
        requests.append(
            {
                "updateCells": {
                    "start": {
                        "sheetId": sheet_id,
                        "rowIndex": row - 1,
                        "columnIndex": col - 1,
                    },
                    "rows": [{"values": [{"userEnteredValue": cell_value(cells[ref])}]}],
                    "fields": "userEnteredValue",
                }
            }
        )
    return requests


def quote(sheet_name: str) -> str:
    """Sheet names here carry spaces and parentheses, so always quote."""
    return "'" + sheet_name.replace("'", "''") + "'"


# src/mousai/sheets.py -> the repo root. Config lives with the code, not with
# whatever directory someone happened to launch from.
ROOT = Path(__file__).resolve().parents[2]


def beside_the_code(path: str | Path) -> Path:
    """Resolve a configured path against the repo root unless it is absolute.

    `.env` and the service-account key are written as relative paths by the
    setup wizard. Resolving them against the working directory meant that
    starting the server from anywhere else found neither, and receipt reading
    silently fell back to "type it in" with no hint as to why.
    """
    found = Path(path)
    return found if found.is_absolute() else ROOT / found


def load_env(path: str = ".env") -> dict[str, str]:
    env: dict[str, str] = {}
    file = beside_the_code(path)
    if not file.is_file():
        return env
    for line in file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


# -- the adapter -----------------------------------------------------------


class Sheets:
    """Authenticated access to the Workbooks in one Drive folder."""

    def __init__(
        self,
        sheets_service,
        drive_service,
        folder_id: str | None = None,
        exclude_ids: frozenset[str] = frozenset(),
    ):
        self._sheets = sheets_service
        self._drive = drive_service
        self.folder_id = folder_id
        # The scratch Workbook tests write to must never be offered as a real
        # destination: it is usually the most recently modified file in the
        # folder, so a "newest wins" default would pick it every time.
        self.exclude_ids = exclude_ids

    @classmethod
    def from_env(cls, path: str = ".env") -> "Sheets":
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        env = load_env(path)
        key = env.get("GOOGLE_APPLICATION_CREDENTIALS")
        if not key or not beside_the_code(key).is_file():
            raise SheetsError(Notice("no_credentials"))
        credentials = service_account.Credentials.from_service_account_file(
            str(beside_the_code(key)), scopes=SCOPES
        )
        scratch = env.get("MOUSAI_TEST_SPREADSHEET_ID")
        return cls(
            build("sheets", "v4", credentials=credentials, cache_discovery=False),
            build("drive", "v3", credentials=credentials, cache_discovery=False),
            env.get("MOUSAI_DRIVE_FOLDER_ID"),
            frozenset(filter(None, [scratch])),
        )

    def workbooks(self, folder_id: str | None = None) -> list[WorkbookRef]:
        """Every Workbook in the folder, newest first. This is the picker."""
        folder = folder_id or self.folder_id
        if not folder:
            raise SheetsError(Notice("no_folder"))
        response = (
            self._drive.files()
            .list(
                q=(
                    f"'{folder}' in parents "
                    f"and mimeType='{SPREADSHEET_MIME}' and trashed=false"
                ),
                orderBy="modifiedTime desc",
                fields="files(id,name,modifiedTime)",
                pageSize=100,
            )
            .execute()
        )
        return [
            WorkbookRef(id=f["id"], title=f["name"], modified=f["modifiedTime"])
            for f in response.get("files", [])
            if f["id"] not in self.exclude_ids
        ]

    def open(self, spreadsheet_id: str) -> "Workbook":
        return Workbook(self._sheets, spreadsheet_id)


class Workbook:
    """One month's spreadsheet."""

    def __init__(self, service, spreadsheet_id: str):
        self._service = service
        self.id = spreadsheet_id
        self._meta: dict | None = None

    # -- structure ---------------------------------------------------------

    def _metadata(self, refresh: bool = False) -> dict:
        if self._meta is None or refresh:
            self._meta = (
                self._service.spreadsheets()
                .get(spreadsheetId=self.id, fields="properties.title,sheets.properties")
                .execute()
            )
        return self._meta

    @property
    def title(self) -> str:
        return self._metadata()["properties"]["title"]

    def sheet_names(self) -> list[str]:
        return [s["properties"]["title"] for s in self._metadata()["sheets"]]

    def sheet_id(self, name: str) -> int:
        for sheet in self._metadata()["sheets"]:
            if sheet["properties"]["title"] == name:
                return sheet["properties"]["sheetId"]
        raise SheetNotFound(Notice("sheet_missing", {"page": name}))

    def pages_for(self, template: Template) -> list[str]:
        """Candidate Page names for a Fund, by name prefix.

        Only a shortlist for the picker; whether a sheet really is a Page of this
        Fund is settled by reading it, since the marker rows are the truth.
        """
        return [n for n in self.sheet_names() if n.startswith(template.fund)]

    # -- reading -----------------------------------------------------------

    def grids(self, sheet_names: list[str]) -> dict[str, list[list]]:
        """Several sheets in one call, so scanning the Workbook is not N calls."""
        out: dict[str, list[list]] = {}
        for start in range(0, len(sheet_names), 20):
            chunk = sheet_names[start : start + 20]
            response = (
                self._service.spreadsheets()
                .values()
                .batchGet(
                    spreadsheetId=self.id,
                    ranges=[quote(name) for name in chunk],
                    valueRenderOption="UNFORMATTED_VALUE",
                    dateTimeRenderOption="SERIAL_NUMBER",
                )
                .execute()
            )
            for name, block in zip(chunk, response.get("valueRanges", [])):
                out[name] = block.get("values", [])
        return out

    def writable_pages(self) -> list[tuple[str, Template]]:
        """Every sheet that looks like a Page, in Workbook order.

        This is what the picker offers: the user chooses a Page directly rather
        than a Fund, because only they know whether this month's spending goes
        on เงินสดย่อย6 or a page someone opened this morning.
        """
        found = []
        for name in self.sheet_names():
            if name.startswith("_"):
                continue
            template = fund_for_page(name)
            if template is not None:
                found.append((name, template))
        return found

    def requesters(self) -> list[str]:
        """Names already used in the ผู้เบิก column, most frequent first.

        Harvested rather than stored: whoever is in the Workbook is offered, and
        a name typed by hand today is in the list tomorrow because it is then in
        the column. Nothing to maintain.
        """
        pages = self.writable_pages()
        grids = self.grids([name for name, _ in pages])
        counts: dict[str, int] = {}
        for name, template in pages:
            grid = grids.get(name, [])
            try:
                page = Page(name, template, grid)
            except PageError:
                continue
            column = column_index(template.requester) - 1
            for number in range(page.first_row, page.last_row + 1):
                if number - 1 >= len(grid):
                    break
                line = grid[number - 1]
                if column >= len(line):
                    continue
                value = str(line[column]).strip()
                if value and value not in ("-", "None"):
                    counts[value] = counts.get(value, 0) + 1
        return sorted(counts, key=lambda n: (-counts[n], n))

    def grid(self, sheet_name: str) -> list[list]:
        response = (
            self._service.spreadsheets()
            .values()
            .get(
                spreadsheetId=self.id,
                range=quote(sheet_name),
                valueRenderOption="UNFORMATTED_VALUE",
                dateTimeRenderOption="SERIAL_NUMBER",
            )
            .execute()
        )
        return response.get("values", [])

    def page(self, sheet_name: str, template: Template) -> Page:
        return Page(sheet_name, template, self.grid(sheet_name))

    # -- the config tab ----------------------------------------------------

    def active_page(self, fund: str) -> str | None:
        """The Page new Entries go to, or None when nothing has been remembered."""
        if CONFIG_SHEET not in self.sheet_names():
            return None
        rows = (
            self._service.spreadsheets()
            .values()
            .get(spreadsheetId=self.id, range=f"{CONFIG_SHEET}!A:B")
            .execute()
            .get("values", [])
        )
        for row in rows[1:]:
            if len(row) >= 2 and row[0] == fund:
                return row[1] or None
        return None

    def remember_page(self, fund: str, sheet_name: str) -> None:
        """Record the active Page, creating the hidden config tab on first use."""
        if CONFIG_SHEET not in self.sheet_names():
            self._service.spreadsheets().batchUpdate(
                spreadsheetId=self.id,
                body={
                    "requests": [
                        {
                            "addSheet": {
                                "properties": {
                                    "title": CONFIG_SHEET,
                                    "hidden": True,
                                }
                            }
                        }
                    ]
                },
            ).execute()
            self._metadata(refresh=True)
            rows = [CONFIG_HEADER]
        else:
            rows = (
                self._service.spreadsheets()
                .values()
                .get(spreadsheetId=self.id, range=f"{CONFIG_SHEET}!A:B")
                .execute()
                .get("values", [])
            ) or [CONFIG_HEADER]

        body = [rows[0] if rows else CONFIG_HEADER]
        replaced = False
        for row in rows[1:]:
            if row and row[0] == fund:
                body.append([fund, sheet_name])
                replaced = True
            else:
                body.append(row)
        if not replaced:
            body.append([fund, sheet_name])

        self._service.spreadsheets().values().update(
            spreadsheetId=self.id,
            range=f"{CONFIG_SHEET}!A1",
            valueInputOption="RAW",
            body={"values": body},
        ).execute()

    # -- writing -----------------------------------------------------------

    def append(self, page: Page, placement) -> None:
        """Write one Entry, re-checking the target row first.

        The Workbook is live and multi-user: between the preview and the Confirm
        someone can type into the row we picked. Writing anyway would corrupt
        every balance below it, silently, so a taken row is refused.
        """
        fresh = self.page(page.name, page.template)
        if fresh.free_row != placement.row:
            raise RowTaken(
                Notice("row_taken", {"page": page.name, "row": placement.row})
            )
        self._service.spreadsheets().batchUpdate(
            spreadsheetId=self.id,
            body={
                "requests": build_update_requests(
                    self.sheet_id(page.name), placement.cells
                )
            },
        ).execute()
