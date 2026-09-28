# Notifications to Keepers and the operator

Status: ready-for-agent
Blocked by: 10

## Scope

- **Keepers:** each saved Entry (who, what, amount, Page, row, balance); a Page
  with two or fewer free rows left; a negative Balance; each no-receipt spend.
- **Operator:** access requests, and failures of OCR, the LLM, Sheets or the bot
  itself.
- Book matters never go to the operator unless they are also a Keeper.

## Done when

- Tests that each event reaches the right people and nobody else.
