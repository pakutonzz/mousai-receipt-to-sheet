"""Record one Entry, end to end. A command-line stand-in for the preview screen.

Picks the Workbook, resolves the active Page, works out the target row, shows
you everything it is about to do, and writes only after you say yes.

    python scripts/add_entry.py --amount 23 --description "ค่าขนมปังรับรองลูกค้า"

    python scripts/add_entry.py --fund เงินฉุกเฉิน --amount 780 \
        --description "ค่าขยะติดเชื้อ" --date 1/9/2026

Dates are day/month/year, matching the Workbook. `--dry-run` previews without
writing. `--yes` skips the prompt and exists for the scripted acceptance run;
the app itself will always ask a human.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mousai import BY_FUND, PETTY_CASH, Formula, PageError  # noqa: E402
from mousai.messages import Notice, english  # noqa: E402
from mousai.sheets import Sheets, SheetsError, load_env  # noqa: E402

DATE_FORMATS = ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d")


def parse_date(text: str) -> dt.date:
    """Day first, because that is how the Workbook and the team read dates."""
    for fmt in DATE_FORMATS:
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(
        f"unrecognised date {text!r}; use d/m/yyyy, e.g. 3/8/2026"
    )


def describe(value) -> str:
    return value.text if isinstance(value, Formula) else repr(value)


def choose_workbook(sheets: Sheets, explicit: str | None):
    if explicit:
        return sheets.open(explicit), None
    found = sheets.workbooks()
    if not found:
        raise SheetsError(Notice("no_workbooks"))
    return sheets.open(found[0].id), found


def choose_page(workbook, template, explicit: str | None) -> str:
    if explicit:
        return explicit
    remembered = workbook.active_page(template.fund)
    if remembered:
        return remembered
    candidates = workbook.pages_for(template)
    raise SheetsError(
        Notice(
            "no_page_remembered",
            {
                "fund": template.fund,
                "candidates": ", ".join(candidates) or "(none found)",
            },
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--amount", type=float, required=True)
    parser.add_argument("--description", required=True)
    parser.add_argument("--fund", default=PETTY_CASH.fund, choices=list(BY_FUND))
    parser.add_argument("--date", type=parse_date, default=dt.date.today())
    parser.add_argument("--requester", default="-")
    parser.add_argument("--note", default=None)
    parser.add_argument("--page", default=None, help="override the remembered Page")
    parser.add_argument("--workbook", default=None, help="spreadsheet id")
    parser.add_argument(
        "--scratch",
        action="store_true",
        help="use MOUSAI_TEST_SPREADSHEET_ID; the picker never offers it",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-remember", action="store_true")
    parser.add_argument("--yes", action="store_true", help="skip the confirmation")
    args = parser.parse_args(argv)

    template = BY_FUND[args.fund]

    workbook_id = args.workbook
    if args.scratch:
        workbook_id = load_env().get("MOUSAI_TEST_SPREADSHEET_ID")
        if not workbook_id:
            print("no MOUSAI_TEST_SPREADSHEET_ID in .env", file=sys.stderr)
            return 1
        print("\n  using the scratch Workbook")

    try:
        sheets = Sheets.from_env()
        workbook, listing = choose_workbook(sheets, workbook_id)
        if listing and len(listing) > 1:
            print(f"{len(listing)} Workbooks in the folder; using the newest.")
        page_name = choose_page(workbook, template, args.page)
        page = workbook.page(page_name, template)
        placement = page.place(
            on=args.date,
            description=args.description,
            amount=args.amount,
            requester=args.requester,
            note=args.note,
        )
    except (SheetsError, PageError) as error:
        print(f"\n{error}\n", file=sys.stderr)
        return 1

    print(f"\n  Workbook   {workbook.title}")
    print(f"  Page       {page_name}   rows {page.first_row}-{page.last_row}")
    print(f"  Above      row {page.last_entry.number}, balance {page.last_entry.balance:,.2f}")
    print()
    print(f"  Date       {args.date:%d/%m/%Y}" + ("" if placement.write_date else "   (same day as the row above, left blank)"))
    print(f"  Sequence   {placement.sequence}")
    print(f"  Detail     {args.description}")
    print(f"  Amount     {args.amount:,.2f}")
    print(f"  Balance    {placement.balance:,.2f}")
    print(f"  Requester  {args.requester}")
    if args.note:
        print(f"  Note       {args.note}")
    print()
    print(f"  Writing to row {placement.row}, {placement.rows_remaining} row(s) left after this:")
    for ref in sorted(placement.cells):
        print(f"      {ref:6s} {describe(placement.cells[ref])}")

    for warning in placement.warnings:
        print(f"\n  ! {warning}")

    if args.dry_run:
        print("\n  dry run: nothing written.\n")
        return 0

    if not args.yes:
        print()
        answer = input("  Write this Entry? [y/N] ").strip().lower()
        if not answer.startswith("y"):
            print("  cancelled, nothing written.\n")
            return 1

    try:
        workbook.append(page, placement)
    except (SheetsError, PageError) as error:
        print(f"\n{error}\n", file=sys.stderr)
        return 1

    print(f"\n  written to {page_name}!{placement.row}")
    if not args.no_remember and args.page:
        workbook.remember_page(template.fund, page_name)
        print(f"  remembered {page_name} as the active Page for {template.fund}")
    print(f"  https://docs.google.com/spreadsheets/d/{workbook.id}/edit\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
