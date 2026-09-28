# A local store for the Queue and the same-photo index

Status: resolved

Queued Transactions and the photos already recorded need to survive a restart
of the bot. They live in a small database on the Mac, never in the Workbook:
nothing unconfirmed belongs in the cash book.

## Scope

- A Transaction's fields, who handed it in, the photo's Telegram file IDs, its
  state (open, queued, confirmed, rejected with a reason, cancelled, expired),
  and the chat messages that show it, so they can be edited later: the
  Recorder's and each Keeper's copy.
- The same-photo index: a photo's Telegram `file_unique_id` → Workbook, Page,
  row and Description of the Entry it became.
- Single process, SQLite from the standard library. The file sits beside the
  app, outside git.

## Done when

- Tests for each state change, including that a confirmed or rejected
  Transaction cannot be acted on again.
- Deleting the file and restarting leaves the bot working with an empty Queue.
