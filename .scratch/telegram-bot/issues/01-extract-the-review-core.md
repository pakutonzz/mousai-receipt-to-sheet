# Extract the Review core out of web.py

Status: ready-for-agent

`web.py` holds, inline in its routes, everything that makes writing safe: the
cached Page read for previews, `check_book`, `labelled_cells`, `fingerprint`,
and Confirm's fresh read plus key check. The bot needs exactly the same path,
and two copies of "what was shown is what gets written" would drift.

## Scope

- One module both the web page and the bot call: given the fields of a
  Transaction, produce its Review (cells, warnings, key); given fields plus a
  key, confirm or refuse as stale. Sheets and the clock are injected, as now.
- Pure refactor: no behaviour change, no route change.
- `cells_for_display` stays as its author wrote it.

## Done when

- `web.py` routes are thin: parse the form, call the core, render.
- Every existing web and access test passes unchanged.
- The core has its own tests for stale keys, full Pages and unknown Workbooks
  that do not go through HTTP.
