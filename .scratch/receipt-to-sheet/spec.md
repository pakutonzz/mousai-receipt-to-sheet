# Receipt → Sheet

Capture a spend, check it, write it into the right row of the clinic's cash
Workbook. Agreed in full over a grilling session; this records the outcome.

Vocabulary is in [CONTEXT.md](../../CONTEXT.md). Two decisions have ADRs:
[Google Sheets as system of record](../../docs/adr/0001-google-sheets-as-system-of-record.md)
and [write cells with explicit types](../../docs/adr/0002-write-cells-with-explicit-types.md).

## Flow

Photo or form → pick the Page and the requester → preview the parsed values →
Confirm → one Entry appears in the correct row.

Every field is editable in the preview. Nothing is ever written without a human
confirming it.

## Storage and access

- Google Sheets is authoritative. The `.xlsx` is a read-only audit archive the
  app never reads or writes.
- A **service account** authenticates. The Drive **folder** is shared with it
  once, so each new monthly Workbook inherits access with no setup.
- The app lists spreadsheets in that folder as a picker, defaulting to the most
  recently modified.
- Attribution is free: app-written cells name the service account in *Show edit
  history*. No marker column, nothing extra on the printout.

## Finding the target cell

- **The data region is discovered, never configured.** Locate the row whose date
  column holds the Template's header marker, and the row holding `รวมทั้งสิ้น`;
  Entries go strictly between them. Required, because regions differ per Page —
  24, 25, 26, 28 and 32 rows across the petty-cash Pages alone.
- A **Template** carries the column letters and the header marker for one Fund.
  เงินสดย่อย starts at column B, เงินฉุกเฉิน at column A, and the certificate
  sheets head their date column `วันที่` rather than `ว/ด/ป`.
- **The user picks a Page directly**, not a Fund: every writable Page in the
  Workbook is offered, grouped by Fund, because only the person spending knows
  whether this goes on เงินสดย่อย6 or a page opened this morning. The Fund
  follows from the Page's name, so there is nothing to keep in step.
- The hidden config tab still records the last Page used per Fund, written on
  the first successful Confirm behind a "remember this Page" checkbox. It marks
  that Page with ● and preselects it. It is a default, never a restriction.
- The preview always shows the target Page and row, and the user can change
  either before confirming.

## Writing an Entry

- `spreadsheets.batchUpdate` / `updateCells`, each cell explicitly typed, with
  `fields: "userEnteredValue"` so a write cannot disturb formatting.
- Date as a serial number. Balance as a live formula `=G{prev}-F{row}`. `"-"` in
  the ยอดรับ column. The note goes in the column labelled ผู้อนุมัติ, which has
  never held an approver's name.
- **Requester is a dropdown, harvested from the ผู้เบิก column** of the
  Workbook's own Pages, most used first, plus `-` and a free-text option. No
  list to maintain: a name typed by hand today is offered tomorrow, because by
  then it is in the column.
- **Date and sequence**: a new date writes the date and starts the sequence at 1;
  the same date as the row above leaves the date blank and continues the
  sequence. A date earlier than the row above warns but still appends.
- Re-read the target row immediately before writing; abort if it is no longer
  empty.

## Refuse, or warn

| Situation | Behaviour |
| --- | --- |
| Data region full | Error. No Page is created automatically. |
| Page has no opening row | Error — ask for a `ยกยอดมา` row first. |
| Resulting balance negative | Warn, allow. It has happened before. |
| Date earlier than the row above | Warn, allow. Backdating is normal here. |
| Last row carries a Top-up | Warn — Top-ups are out of scope this phase. |
| Fewer than 3 rows left | Warn — see `issues/01`. |

## Out of scope this phase

Top-ups and the Ledger sheets, creating Pages, writing a certificate alongside
an Entry, and any automatic update of the summary sheets.

OCR was out of scope until the write path was proven; it is now built on Google
Cloud Vision, using the same service account as Sheets. Vision extracts the
text and `receipt.py` picks the amount by ranked keywords, pairing labels to
right-column amounts using word bounding boxes. It is never required: a disabled
API, an exhausted quota, a dead network or an unreadable photo all degrade to a
Thai note and manual typing, and nothing OCR produces is written without a
person confirming it.

## Getting to production

1. `scripts/setup-google-access.sh` — service account, key, folder share.
2. `scripts/reconcile.py` — prove the converted Workbook matches the `.xlsx`
   baseline before anyone trusts it.
3. Reformat the date columns to `dd/mm/yyyy`; the import left them `m/d/yyyy`
   and a locale change does not fix cells carrying an explicit format.
4. `scripts/add_entry.py --dry-run …` against the scratch copy in
   `M_example_sheets`, then without `--dry-run`, until the acceptance test below
   passes for real. Only then point at the live Workbook — config, not code.
5. Hard cutover. No parallel running. Mark the `.xlsx` read-only.

## Acceptance test

23 baht, `ค่าขนมปังรับรองลูกค้า`, Fund เงินสดย่อย. Lands on `เงินสดย่อย6` row 21
with the right date, sequence, description and amount; a balance that computes;
no existing row touched; formatting intact; the totals line and signature block
untouched.

Note the closing balance of that Page is 20.25, so this Entry resolves to
−2.75 and must raise the negative-balance warning rather than being blocked.

## Cutover log

Completed 21 September 2026.

| Step | Outcome |
| --- | --- |
| Service account, key, folder share | `scripts/setup-google-access.sh`; folder shared, not the file, so future Workbooks inherit access |
| Reconciliation | 1,634 cells and 159 formulas match the `.xlsx` baseline across all 21 sheets, on both the live Workbook and the scratch copy |
| Acceptance test | 23 THB written to `เงินสดย่อย6!21` on the scratch copy; `G21` read back as `-2.75`, so Google evaluated the formula; every baseline cell unchanged |
| Date columns | reformatted to `dd/mm/yyyy` on all 21 sheets; reconcile clean afterwards, proving presentation-only |
| `.xlsx` | read-only, unmodified since 20 September, kept as the audit archive |

Two things the reconciliation caught that nothing else would have: a stray `'p'`
typed into `PT!A1` (absent from the `.xlsx`, since cleared), and the fact that
the check originally only walked cells the baseline knew about, so additions were
invisible to it. It now reports changes and additions separately.

The live Workbook has no `_mousai` config tab yet. The first Entry written with
`--page` creates it, and after that the Page is remembered.
