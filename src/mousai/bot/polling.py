"""Telegram, by long polling: the only module that imports python-telegram-bot.

The bot asks Telegram for new messages rather than Telegram calling in, so
nothing on the machine that runs it is reachable from outside. Messages sent
while it is down wait at Telegram for up to a day and are handled when it comes
back, which is why pending updates are kept, not dropped, at startup.
"""

from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.error import TelegramError
from telegram.constants import ChatType
from telegram.ext import Application, ApplicationBuilder, ContextTypes, MessageHandler, filters

from .core import Bot, Incoming, Send

log = logging.getLogger("mousai.bot")


def incoming_from(update: Update) -> Incoming | None:
    message, chat, user = update.effective_message, update.effective_chat, update.effective_user
    if message is None or chat is None or user is None:
        return None
    return Incoming(
        chat_id=chat.id,
        user_id=user.id,
        private=chat.type == ChatType.PRIVATE,
        text=message.text or message.caption,
        name=user.full_name,
        username=user.username,
    )


async def deliver(send_message, replies: list[Send]) -> int:
    """Send each reply on its own, so one unreachable chat cannot silence the rest.

    The usual failure is "Chat not found": a bot cannot message anyone who has
    never messaged it, which is true of every operator and Keeper until they
    first write to the bot. That is logged as one line, and the others still go.
    """
    sent = 0
    for reply in replies:
        try:
            await send_message(chat_id=reply.chat_id, text=reply.text)
            sent += 1
        except TelegramError as error:
            log.warning("could not message chat %s: %s", reply.chat_id, error)
    return sent


def build(token: str, bot: Bot) -> Application:
    app = ApplicationBuilder().token(token).build()

    async def on_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        incoming = incoming_from(update)
        if incoming is None:
            return
        # The core blocks on Sheets and Vision; keep it off the event loop.
        replies = await asyncio.to_thread(bot.handle, incoming)
        sent = await deliver(context.bot.send_message, replies)
        # Who and how many, never what: messages can name patients.
        log.info(
            "update from %s (%s): %d of %d replies sent",
            incoming.user_id,
            "private" if incoming.private else "group",
            sent,
            len(replies),
        )

    async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        log.error("handling an update failed", exc_info=context.error)

    app.add_handler(MessageHandler(filters.ALL, on_update))
    app.add_error_handler(on_error)
    return app


def run(token: str, bot: Bot) -> None:
    build(token, bot).run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=False)
