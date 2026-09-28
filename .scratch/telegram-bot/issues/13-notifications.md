# Notifications to Keepers and the operator

Status: resolved
Blocked by: 10

## Scope

- **Keepers:** each saved Entry (who, what, amount, Page, row, balance); a Page
  with two or fewer free rows left; a negative Balance; each no-receipt spend.
- **Operator:** access requests, and failures of OCR, the LLM, Sheets or the bot
  itself.
- Book matters never go to the operator unless they are also a Keeper.

## Done when

- Tests that each event reaches the right people and nobody else.

## Comments

**2026-09-28, agent.** Done; `tests/test_bot_notify.py`. Each saved Entry
reaches every other Keeper as a new message (who saved it, what, how much,
Page, row, balance, and who handed it in for a queued one), with the Page's
"only N rows left" and a negative balance in the Keepers' existing wording, and
the no-receipt line. The Keeper who saved it sees the same two warnings in the
saved message. Operators hear of Vision failing, the model not answering (the
describer and the typed-text reader now keep `last_error`), Sheets or the
network failing, and the bot failing on an update; at most once an hour per
kind. An operator who is not a Keeper never hears book matters.
