"""Set every date column to dd/mm/yyyy.

The xlsx import baked Excel's built-in `m/d/yyyy` into each date cell, and that
survives a change of spreadsheet locale, so `46243` still reads `8/9/2026` when
it means 9 August. For any date whose day and month are both twelve or less, the
Workbook is currently telling readers the wrong thing.

This changes presentation only: the field mask is
`userEnteredFormat.numberFormat`, so borders, fonts, fills and the values
themselves cannot be touched. Running `reconcile.py` afterwards should still
report every baseline cell unchanged, which is the proof.

    python scripts/format_dates.py --scratch --dry-run
    python scripts/format_dates.py --scratch
    python scripts/format_dates.py --workbook <id>

The date column is discovered per sheet, the same way the write path finds its
target row: whichever column carries the header marker.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mousai.sheets import Sheets, SheetsError, load_env  # noqa: E402
from mousai.templates import CERTIFICATE_HEADER_MARKER, TOTALS_MARKER  # noqa: E402

DATE_PATTERN = "dd/mm/yyyy"
HEADER_MARKERS = ("ว/ด/ป", CERTIFICATE_HEADER_MARKER)


def locate_date_column(grid: list[list]) -> tuple[int, int, int] | None:
    """Return (column, first_row, last_row), 1-based, or None if not a form.

    The header marker names the date column and opens the region; the totals
    marker closes it. Rows outside are headings and signatures, which must keep
    whatever formatting they have.
    """
    header_row = header_col = totals_row = None
    for row_index, line in enumerate(grid, start=1):
        for col_index, value in enumerate(line, start=1):
            text = str(value).strip()
            if header_row is None and text in HEADER_MARKERS:
                header_row, header_col = row_index, col_index
            elif totals_row is None and text == TOTALS_MARKER:
                totals_row = row_index
    if header_row is None or totals_row is None or totals_row <= header_row + 1:
        return None
    return header_col, header_row + 1, totals_row - 1


def build_format_request(
    sheet_id: int, column: int, first_row: int, last_row: int
) -> dict:
    return {
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": first_row - 1,
                "endRowIndex": last_row,
                "startColumnIndex": column - 1,
                "endColumnIndex": column,
            },
            "cell": {
                "userEnteredFormat": {
                    "numberFormat": {"type": "DATE", "pattern": DATE_PATTERN}
                }
            },
            # Nothing but the number format. Not borders, not fills, not values.
            "fields": "userEnteredFormat.numberFormat",
        }
    }


def plan(workbook) -> tuple[list[dict], list[str]]:
    requests, described, skipped = [], [], []
    for name in workbook.sheet_names():
        if name.startswith("_"):
            continue  # the hidden config tab is ours, not a form
        found = locate_date_column(workbook.grid(name))
        if found is None:
            skipped.append(name)
            continue
        column, first_row, last_row = found
        requests.append(
            build_format_request(workbook.sheet_id(name), column, first_row, last_row)
        )
        letter = chr(ord("A") + column - 1)
        described.append(f"{name}: {letter}{first_row}:{letter}{last_row}")
    for name in skipped:
        described.append(f"{name}: skipped, no data region found")
    return requests, described


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", default=None, help="spreadsheet id")
    parser.add_argument("--scratch", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args(argv)

    workbook_id = args.workbook
    if args.scratch:
        workbook_id = load_env().get("MOUSAI_TEST_SPREADSHEET_ID")
    if not workbook_id:
        print("pass --workbook <id> or --scratch", file=sys.stderr)
        return 1

    try:
        sheets = Sheets.from_env()
        workbook = sheets.open(workbook_id)
        requests, described = plan(workbook)
    except SheetsError as error:
        print(f"\n{error}\n", file=sys.stderr)
        return 1

    print(f"\n  {workbook.title}\n")
    for line in described:
        print(f"    {line}")
    print(f"\n  {len(requests)} sheet(s) to reformat as {DATE_PATTERN}")

    if not requests:
        return 0
    if args.dry_run:
        print("\n  dry run: nothing changed.\n")
        return 0
    if not args.yes:
        answer = input("\n  Apply? [y/N] ").strip().lower()
        if not answer.startswith("y"):
            print("  cancelled.\n")
            return 1

    workbook._service.spreadsheets().batchUpdate(
        spreadsheetId=workbook.id, body={"requests": requests}
    ).execute()
    print(f"\n  done. Re-run reconcile.py: every baseline cell should still match,")
    print(f"  because only the number format changed.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
