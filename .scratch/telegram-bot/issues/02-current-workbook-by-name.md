# Choose the current Workbook by the month in its name

Status: resolved
Blocked by: 01

Today the default Workbook is the folder's most recently *modified* file. A
correction to August's Workbook on 3 September makes August the default again,
and entries land in a month that is closed.

## Scope

- The current Workbook is the one whose name carries the latest month, e.g.
  `เบิกจ่ายเงินสด กันยายน26` over `…สิงหาคม26`: a Thai month name plus a year,
  read the way receipts are (26 is 2026; 69 and 2569 are 2026 too).
- Used by the web page's default and by the bot. Files whose names carry no
  month sort last, and are still selectable by hand.
- A late receipt keeps its true date in the current Workbook; the existing
  backdated warning covers it. No write into the previous month's Workbook
  unless someone picks it explicitly.

## Done when

- Tests over a fake folder where the newest-modified file is not the current
  month, and where one name has no month.
- The web page opens on the current month's Workbook in that case.
