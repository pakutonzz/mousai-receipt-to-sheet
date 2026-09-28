# Spends with no receipt

Status: resolved
Blocked by: 05, 09

A text message is a Transaction without a receipt.

## Scope

- Read through ticket 05, then the same Review and flow as a photo.
- The Note gets **ไม่มีใบเสร็จ**, alongside anything typed there.
- Keepers are told each one needs a receipt-substitute certificate. Writing the
  certificate itself is out of scope.

## Done when

- Tests: a text entry with and without the model, and its Note.

## Comments

**2026-09-28, agent.** Done with ticket 05. Text typed with no Review open is
read as a spend; its Note is ไม่มีใบเสร็จ and stays so whatever is typed into
the Note later; the Review says a receipt-substitute certificate is needed and
so does the saved message. Text with no number in it ("สวัสดี") is not a spend
and gets the help line.
