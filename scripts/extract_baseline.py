"""Extract a comparison baseline from the archived .xlsx.

The .xlsx is a read-only audit copy that never enters the repo (see .gitignore),
so this captures what it contained as a committed JSON fixture. `reconcile.py`
diffs the live Workbook against that fixture to prove the conversion to Google
Sheets lost nothing.

Values only, deliberately. Excel stores repeated formulas as "shared" formulas
where only the first cell carries the text and the rest are back-references;
expanding those to compare formula strings against Sheets would be a translator
we do not otherwise need. Instead each cell records whether it *was* a formula,
so reconcile can assert a balance cell is still computed rather than flattened,
without comparing the text.

Usage:
    python scripts/extract_baseline.py "เบิกจ่ายเงินสด สิงหาคม26.xlsx"
"""

from __future__ import annotations

import json
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
RNS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

DEFAULT_OUT = Path("tests/fixtures/baseline.json")

# The strings that bound a Page's data region. Finding them is how the app
# locates writable rows, so the baseline records them too: if the conversion
# moved or reworded either one, every write target shifts.
#
# Detail Pages and Ledger sheets head the date column "ว/ด/ป"; the certificate
# sheets use "วันที่" instead. A Template names its own marker rather than the
# app assuming one, and this mirrors that.
HEADER_MARKERS = ("ว/ด/ป", "วันที่")
TOTALS_MARKER = "รวมทั้งสิ้น"


def _cell_row(ref: str) -> int:
    return int(re.sub(r"[A-Z]", "", ref))


def _shared_strings(z: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return ["".join(t.text or "" for t in si.iter(NS + "t")) for si in root]


def _sheet_targets(z: zipfile.ZipFile) -> list[tuple[str, str]]:
    book = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    by_id = {r.get("Id"): r.get("Target") for r in rels}
    out = []
    for sheet in book.iter(NS + "sheet"):
        target = by_id[sheet.get(RNS + "id")]
        if not target.startswith("/"):
            target = "xl/" + target
        out.append((sheet.get("name"), target.lstrip("/")))
    return out


def _cell_value(cell: ET.Element, strings: list[str]):
    """Return the cell's value shaped like the Sheets API's UNFORMATTED_VALUE."""
    kind = cell.get("t")
    inline = cell.find(NS + "is")
    if inline is not None:
        return "".join(t.text or "" for t in inline.iter(NS + "t"))
    v = cell.find(NS + "v")
    if v is None or v.text is None:
        return None
    if kind == "s":
        return strings[int(v.text)]
    if kind in ("str", "e"):
        return v.text
    if kind == "b":
        return v.text == "1"
    try:
        num = float(v.text)
    except ValueError:
        return v.text
    return int(num) if num.is_integer() else num


def extract_sheet(z: zipfile.ZipFile, path: str, strings: list[str]) -> dict:
    ws = ET.fromstring(z.read(path))
    cells: dict[str, dict] = {}
    formula_cells: list[str] = []

    for cell in ws.iter(NS + "c"):
        ref = cell.get("r")
        value = _cell_value(cell, strings)
        is_formula = cell.find(NS + "f") is not None
        if value is None and not is_formula:
            continue  # empty-but-styled cell; formatting is not our concern here
        cells[ref] = {"v": value}
        if is_formula:
            cells[ref]["f"] = True
            formula_cells.append(ref)

    header_row = totals_row = header_marker = None
    for ref, cell in cells.items():
        if cell["v"] in HEADER_MARKERS and header_row is None:
            header_row, header_marker = _cell_row(ref), cell["v"]
        elif cell["v"] == TOTALS_MARKER and totals_row is None:
            totals_row = _cell_row(ref)

    region = None
    if header_row is not None and totals_row is not None:
        region = {"first_row": header_row + 1, "last_row": totals_row - 1}

    return {
        "cells": cells,
        "header_marker": header_marker,
        "header_row": header_row,
        "totals_row": totals_row,
        "data_region": region,
        "formula_cells": sorted(formula_cells, key=lambda r: (_cell_row(r), r)),
    }


def extract(xlsx: Path) -> dict:
    with zipfile.ZipFile(xlsx) as z:
        strings = _shared_strings(z)
        sheets = {
            name: extract_sheet(z, path, strings)
            for name, path in _sheet_targets(z)
        }
    return {
        "source_file": xlsx.name,
        "sheet_order": list(sheets),
        "sheets": sheets,
    }


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    xlsx = Path(argv[1])
    if not xlsx.is_file():
        print(f"no such file: {xlsx}", file=sys.stderr)
        return 1

    out = Path(argv[2]) if len(argv) > 2 else DEFAULT_OUT
    baseline = extract(xlsx)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(baseline, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8",
    )

    sheets = baseline["sheets"]
    cells = sum(len(s["cells"]) for s in sheets.values())
    formulas = sum(len(s["formula_cells"]) for s in sheets.values())
    print(f"{out}: {len(sheets)} sheets, {cells} cells, {formulas} formulas")
    for name in baseline["sheet_order"]:
        s = sheets[name]
        region = s["data_region"]
        span = (
            f"rows {region['first_row']}-{region['last_row']}"
            if region
            else "no data region"
        )
        print(f"  {name:24s} {len(s['cells']):4d} cells  {span}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
