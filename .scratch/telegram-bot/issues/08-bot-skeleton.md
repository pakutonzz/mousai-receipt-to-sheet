# The bot: long polling and the door

Status: ready-for-human
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

## Comments

**2026-09-28, agent.** The code is done and tested: `src/mousai/bot/core.py`
(the conversation, no Telegram in it), `src/mousai/bot/polling.py` (the only
module that imports python-telegram-bot), `scripts/bot.py`. Strangers get their
ID; operators hear once a day per stranger; groups get silence; a broken
people-file edit is reported to operators once. The live check in "Done when"
waits for the bot token in the Mac's `.env` and a real `people.toml` there.

**2026-09-28, agent.** Live on the Mac as the LaunchAgent `com.mousai.bot`.
A first message from an unlisted account got its Telegram ID back. The access
request to the placeholder operator failed with "Chat not found", which showed
that one failed send aborted the rest of the batch; sends are now independent
and a failure is one warning line. Left: a message from a listed Keeper after
the people file has real IDs.
