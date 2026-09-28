# The bot: long polling and the door

Status: ready-for-agent
Blocked by: 06

## Scope

- `scripts/bot.py` runs the bot with long polling, reading `TELEGRAM_BOT_TOKEN`
  from `.env`. Nothing listens for inbound connections.
- Private chats only; messages from groups are ignored.
- A sender not on the list gets their Telegram ID and "ส่งรหัสนี้ให้ผู้ดูแล",
  and the operator is told who asked. Nothing else is revealed.
- All wording goes through `messages.py` as Notices, Thai for chats. No prose
  built inline.
- Telegram and Sheets are behind interfaces so the flows can be tested without
  either.

## Done when

- Tests: a stranger, a Recorder and a Keeper each sending `/start`.
- Started by hand on the Mac, it answers a Keeper and a stranger correctly.
