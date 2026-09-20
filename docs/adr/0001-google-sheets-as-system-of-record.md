# Google Sheets as the system of record

The clinic's cash-disbursement records lived in a 21-sheet `.xlsx` workbook on one laptop. Rather than have the app edit that file in place, we converted the workbook to Google Sheets and made the Sheet the authoritative copy; the app writes Entries through the Sheets API and the `.xlsx` is archived. We did this because writing back into the `.xlsx` was the riskiest part of the whole system and Google Sheets deletes that risk entirely rather than mitigating it.

## Considered Options

**`openpyxl` round-trip** — load the workbook, write a cell, save. Rejected: openpyxl re-serialises every part of the file, dropping the cached value of every formula, the per-sheet printer settings and `calcChain`, on a workbook carrying 15 drawings and 21 print configurations. Too much collateral damage for a one-cell change.

**In-place OOXML surgery** — treat the `.xlsx` as a zip, edit only the target sheet's XML, copy every other part byte-for-byte. This was the plan for most of the design discussion and it is the highest-fidelity option: you can assert that exactly one part of the archive changed. Rejected on cost and on two problems it could not solve:

- *The app cannot read its own writes.* A balance written as `=G20-F21` has no computed result in the file until Excel next opens it, so the following Entry would compute its balance against a blank cell. Workable only by writing a cached value alongside every formula.
- *Lost updates are unavoidable.* When the workbook is open in Excel, Excel holds its own copy; a write underneath it is silently erased by the user's next Save. A lock-file check narrows the window but cannot close it. This was not hypothetical — Excel was holding the file open, unnoticed, during the design session.

**Google Sheets** — chosen. A values-only write leaves cell formatting untouched, so the pre-formatted empty rows in each Page's data region survive. Concurrent editing is the normal case rather than a hazard. Version history and per-cell edit attribution come free, replacing a `backups/` folder and an audit log we would otherwise have had to build.

## Consequences

- **Printing survives, contrary to what we expected.** The per-sheet print scales in the source (60–86%) do not carry over, but Google's own "fit to page" default produces the same result: `เงินสดย่อย6` previews as a single A4 portrait page with the document head, the full bordered table, the totals line and the signature block intact. The print cost that nearly kept us on `.xlsx` turned out to be close to zero. Margins import as a custom 0 cm on all four sides, which should be raised before anyone prints for real.
- **The conversion was imperfect.** At least one Page (`เงินสดย่อย3 (2)`) came through with broken formatting. It is a closed Page the app never writes to, and the layout is being fixed by hand.
- **Tests need a network or a fake.** The `.xlsx` route offered offline, deterministic tests against a fixture file. Sheets does not. Expect one real end-to-end test against a scratch spreadsheet and fakes elsewhere.
- **Hosting is now open.** The app no longer has to run on the machine holding the file, which the `.xlsx` route made impossible.
- The domain logic — locating a Page's data region, finding the free row, the date-and-sequence rule, computing the balance — is unaffected by this decision and sits above the storage adapter.
