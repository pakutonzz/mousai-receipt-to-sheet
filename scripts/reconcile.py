"""Diff the live Google Sheets Workbook against the .xlsx baseline.

Proves the conversion lost nothing before anyone trusts the converted copy.
Run this once after `setup-google-access.sh`, and again any time you suspect
the Workbook has drifted.

    python scripts/reconcile.py                  # the id in .env
    python scripts/reconcile.py <spreadsheet-id> # or an explicit one

Exits non-zero when anything differs, so it can gate the cutover.

Compares values, not formula text: see the note in extract_baseline.py. A
balance cell is checked for *still being a formula*, which is the property that
matters — a flattened balance silently stops tracking the rows above it.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

BASELINE = Path("tests/fixtures/baseline.json")
SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"

# Money is stored to 2dp; anything below this is float representation noise,
# not a real difference.
TOLERANCE = 1e-6


def load_env(path: str = ".env") -> dict[str, str]:
    env: dict[str, str] = {}
    p = Path(path)
    if not p.is_file():
        return env
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def a1_to_rowcol(ref: str) -> tuple[int, int]:
    """'D21' -> (21, 4), both 1-based."""
    match = re.fullmatch(r"([A-Z]+)(\d+)", ref)
    if not match:
        raise ValueError(f"bad cell ref: {ref}")
    letters, row = match.groups()
    col = 0
    for ch in letters:
        col = col * 26 + (ord(ch) - ord("A") + 1)
    return int(row), col


def quote_range(sheet_name: str) -> str:
    """Sheet names here carry spaces and parentheses, so always quote."""
    return "'" + sheet_name.replace("'", "''") + "'"


def same(expected, actual) -> bool:
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        if isinstance(actual, str):
            try:
                actual = float(actual)
            except ValueError:
                return False
        if not isinstance(actual, (int, float)) or isinstance(actual, bool):
            return False
        return abs(float(expected) - float(actual)) <= TOLERANCE
    if expected is None:
        return actual in (None, "")
    return str(expected) == str(actual)


def rowcol_to_a1(row: int, col: int) -> str:
    letters = ""
    while col:
        col, remainder = divmod(col - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return f"{letters}{row}"


def cell_at(grid: list[list], row: int, col: int):
    """Sheets omits trailing empties, so treat anything past the edge as blank."""
    if row - 1 >= len(grid):
        return None
    line = grid[row - 1]
    if col - 1 >= len(line):
        return None
    value = line[col - 1]
    return None if value == "" else value


def fetch(service, spreadsheet_id: str, sheet_names: list[str], render: str) -> dict:
    """One batchGet per render mode; Sheets caps ranges per call, so chunk."""
    grids: dict[str, list[list]] = {}
    for start in range(0, len(sheet_names), 20):
        chunk = sheet_names[start : start + 20]
        response = (
            service.spreadsheets()
            .values()
            .batchGet(
                spreadsheetId=spreadsheet_id,
                ranges=[quote_range(n) for n in chunk],
                valueRenderOption=render,
                dateTimeRenderOption="SERIAL_NUMBER",
            )
            .execute()
        )
        for name, block in zip(chunk, response.get("valueRanges", [])):
            grids[name] = block.get("values", [])
    return grids


def reconcile(baseline: dict, values: dict, formulas: dict) -> tuple[list[str], list[str]]:
    """Return (changed, added).

    `changed` is anything the baseline recorded that the live Workbook now
    disagrees about: a lost sheet, an altered value, a flattened formula, a moved
    marker row. Those are faults.

    `added` is a cell the live Workbook has and the baseline does not. After the
    first Entry is written that is entirely expected, so it is reported
    separately rather than failing the run — but right after a write it is the
    proof that only the intended cells were touched.
    """
    problems: list[str] = []
    added: list[str] = []

    for name in baseline["sheet_order"]:
        sheet = baseline["sheets"][name]
        if name not in values:
            problems.append(f"{name}: sheet missing from the live Workbook")
            continue

        grid = values[name]
        formula_grid = formulas.get(name, [])

        for row_index, line in enumerate(grid, start=1):
            for col_index, value in enumerate(line, start=1):
                if value in ("", None):
                    continue
                ref = rowcol_to_a1(row_index, col_index)
                if ref not in sheet["cells"]:
                    added.append(f"{name}!{ref} = {value!r}")

        for ref, expected in sorted(sheet["cells"].items()):
            row, col = a1_to_rowcol(ref)
            actual = cell_at(grid, row, col)
            if not same(expected["v"], actual):
                problems.append(
                    f"{name}!{ref}: expected {expected['v']!r}, live has {actual!r}"
                )

        for ref in sheet["formula_cells"]:
            row, col = a1_to_rowcol(ref)
            live = cell_at(formula_grid, row, col)
            if not (isinstance(live, str) and live.startswith("=")):
                problems.append(
                    f"{name}!{ref}: was a formula, live is now a fixed value ({live!r})"
                )

        # The write path finds its target row from these two markers, so a shift
        # here silently redirects every future Entry.
        for label, expected_row in (
            ("header", sheet["header_row"]),
            ("totals", sheet["totals_row"]),
        ):
            if expected_row is None:
                continue
            marker = (
                sheet["header_marker"] if label == "header" else "รวมทั้งสิ้น"
            )
            found = [
                r
                for r, line in enumerate(grid, start=1)
                if any(str(c).strip() == marker for c in line)
            ]
            if expected_row not in found:
                problems.append(
                    f"{name}: {label} marker {marker!r} expected on row "
                    f"{expected_row}, found on {found or 'no row'}"
                )

    return problems, added


def main(argv: list[str]) -> int:
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError:
        print(
            "missing deps. pip install -r requirements.txt",
            file=sys.stderr,
        )
        return 1

    if not BASELINE.is_file():
        print(
            f"no baseline at {BASELINE}. Run scripts/extract_baseline.py first.",
            file=sys.stderr,
        )
        return 1

    env = load_env()
    key_path = env.get("GOOGLE_APPLICATION_CREDENTIALS") or os.environ.get(
        "GOOGLE_APPLICATION_CREDENTIALS"
    )
    spreadsheet_id = (
        argv[1]
        if len(argv) > 1
        else env.get("MOUSAI_SPREADSHEET_ID") or env.get("MOUSAI_TEST_SPREADSHEET_ID")
    )

    if not key_path or not Path(key_path).is_file():
        print(
            "no service account key. Run scripts/setup-google-access.sh first.",
            file=sys.stderr,
        )
        return 1
    if not spreadsheet_id:
        print(
            "no spreadsheet id. Pass one, or set MOUSAI_SPREADSHEET_ID in .env.",
            file=sys.stderr,
        )
        return 1

    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    names = baseline["sheet_order"]

    credentials = service_account.Credentials.from_service_account_file(
        key_path, scopes=[SCOPE]
    )
    service = build("sheets", "v4", credentials=credentials, cache_discovery=False)

    print(f"reading {len(names)} sheets from {spreadsheet_id}")
    values = fetch(service, spreadsheet_id, names, "UNFORMATTED_VALUE")
    formulas = fetch(service, spreadsheet_id, names, "FORMULA")

    problems, added = reconcile(baseline, values, formulas)
    checked = sum(len(s["cells"]) for s in baseline["sheets"].values())

    if added:
        print(f"\n{len(added)} cell(s) added since the baseline:\n")
        for entry in added:
            print(f"  + {entry}")

    if not problems:
        print(f"\nOK: {checked} baseline cells unchanged across {len(names)} sheets")
        return 0

    print(f"\n{len(problems)} difference(s) against the baseline:\n")
    for problem in problems:
        print(f"  {problem}")
    print(f"\nchecked {checked} cells across {len(names)} sheets")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
