# The list of Recorders and Keepers

Status: resolved

Who may use the bot is a file edited by hand.

## Scope

- One entry per person: Telegram user ID, name, default Requester, and role:
  `keeper` or `recorder`. One or more `operator` IDs receive system messages.
- The real file holds IDs and names, so it is gitignored; a committed example
  shows the format. Its path is set in `.env`.
- Checked at startup with messages that say which line is wrong: duplicate IDs,
  no Keeper at all, unknown role. A default Requester that is not yet in the
  Workbook's ผู้เบิก column is allowed, since the column only learns a name
  once it is used.
- Read again on change without restarting the bot.

## Done when

- Tests for a valid file and for each refusal.
- The example file documents every field in Thai and English.
