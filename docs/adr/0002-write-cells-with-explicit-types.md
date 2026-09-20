# Write cells with explicit types, not `values.update`

Entries are written with `spreadsheets.batchUpdate` / `updateCells`, setting each cell's `userEnteredValue` explicitly — `numberValue` for the date serial and the amount, `stringValue` for the description, `formulaValue` for the balance — with `fields: "userEnteredValue"`. The obvious alternative, `values.update` with `valueInputOption: USER_ENTERED`, is shorter and is deliberately not used.

Two reasons, either sufficient on its own:

- **`USER_ENTERED` parses every field.** A description typed as `=SUM(A:A)` or beginning with `+` or `-` becomes a live formula inside a financial record. Descriptions in this domain routinely begin with punctuation and are copied off receipts, so this is not hypothetical. `RAW` would avoid it but cannot write the balance formula.
- **`fields: "userEnteredValue"` cannot touch formatting.** Every Page's data region has empty rows pre-formatted with borders and the accounting number format, and that formatting is why an Entry can be written without painting anything. Restricting the field mask makes "the write cannot disturb the form" a guarantee rather than an expectation.

It also removes locale from the picture: dates go in as serial numbers rather than strings for Google to interpret, which matters because this spreadsheet's date cells carry an `m/d/yyyy` format imported from Excel that survived a change of the spreadsheet locale.

The cost is a slightly wordier call. Anyone tempted to simplify it back to `values.update` should reintroduce both problems knowingly.
