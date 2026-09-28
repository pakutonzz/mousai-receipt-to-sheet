"""Telegram, by long polling: the only module that imports python-telegram-bot.

The bot asks Telegram for new messages rather than Telegram calling in, so
nothing on the machine that runs it is reachable from outside. Messages sent
while it is down wait at Telegram for up to a day and are handled when it comes
back, which is why pending updates are kept, not dropped, at startup.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from pathlib import Path
from typing import Callable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction, ChatType, ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .core import Bot, Incoming, Photo, Send

log = logging.getLogger("mousai.bot")

# An image sent as a file rather than a photo is read too, up to this size.
# Telegram shrinks photos itself; files arrive as they were.
MAX_IMAGE_FILE = 10 * 1024 * 1024

# How long a worker thread waits for Telegram to hand over a photo.
DOWNLOAD_TIMEOUT = 60

# How often the daily Queue reminder is checked for; the core decides.
REMIND_CHECK = 10 * 60


def _photo(message, fetch: Callable[[str], bytes] | None) -> Photo | None:
    if fetch is None or message is None:
        return None
    if message.photo:
        largest = message.photo[-1]
        return Photo(largest.file_id, largest.file_unique_id, lambda: fetch(largest.file_id))
    document = message.document
    if (
        document is not None
        and (document.mime_type or "").startswith("image/")
        and (document.file_size or 0) <= MAX_IMAGE_FILE
    ):
        return Photo(
            document.file_id,
            document.file_unique_id,
            lambda: fetch(document.file_id),
            document.mime_type,
        )
    return None


def incoming_from(update: Update, fetch: Callable[[str], bytes] | None = None) -> Incoming | None:
    """The update as the core sees it. `fetch` downloads a file by its id."""
    chat, user = update.effective_chat, update.effective_user
    if chat is None or user is None:
        return None
    private = chat.type == ChatType.PRIVATE
    query = update.callback_query
    if query is not None:
        return Incoming(
            chat_id=chat.id,
            user_id=user.id,
            private=private,
            name=user.full_name,
            username=user.username,
            button=query.data,
            message_id=query.message.message_id if query.message else None,
        )
    message = update.effective_message
    if message is None:
        return None
    return Incoming(
        chat_id=chat.id,
        user_id=user.id,
        private=private,
        text=message.text or message.caption,
        name=user.full_name,
        username=user.username,
        photo=_photo(message, fetch),
        album=message.media_group_id,
        message_id=message.message_id,
    )


def _markup(reply: Send) -> InlineKeyboardMarkup | None:
    rows = [
        [InlineKeyboardButton(b.text, callback_data=b.data) for b in row]
        for row in reply.buttons
        if row
    ]
    return InlineKeyboardMarkup(rows) if rows else None


async def deliver(telegram, replies: list[Send], remember=None) -> int:
    """Send or edit each reply on its own, so one failure cannot silence the rest.

    The usual failure is "Chat not found": a bot cannot message anyone who has
    never messaged it, which is true of every operator and Keeper until they
    first write to the bot. That is logged as one line, and the others still go.

    An edit that Telegram refuses (the message is too old, or was deleted) is
    sent as a new message instead. `remember(txn_id, chat_id, message_id, kind)`
    records where a Review or a Queue card went, so the next change can edit it.
    """
    sent = 0
    for reply in replies:
        parse_mode = ParseMode.HTML if reply.html else None
        try:
            message = None
            if reply.edit is not None:
                try:
                    if reply.caption:
                        message = await telegram.edit_message_caption(
                            chat_id=reply.chat_id,
                            message_id=reply.edit,
                            caption=reply.text,
                            parse_mode=parse_mode,
                            reply_markup=_markup(reply),
                        )
                    else:
                        message = await telegram.edit_message_text(
                            reply.text,
                            chat_id=reply.chat_id,
                            message_id=reply.edit,
                            parse_mode=parse_mode,
                            reply_markup=_markup(reply),
                        )
                except BadRequest as error:
                    if "not modified" not in str(error).lower():
                        log.info("could not edit a message in chat %s: %s", reply.chat_id, error)
                        message = None
                    else:
                        message = True
            if message is None and reply.photo is not None:
                message = await telegram.send_photo(
                    chat_id=reply.chat_id,
                    photo=reply.photo,
                    caption=reply.text,
                    parse_mode=parse_mode,
                    reply_markup=_markup(reply),
                )
            elif message is None:
                message = await telegram.send_message(
                    chat_id=reply.chat_id,
                    text=reply.text,
                    parse_mode=parse_mode,
                    reply_markup=_markup(reply),
                )
            sent += 1
            message_id = getattr(message, "message_id", None)
            if remember is not None and reply.remember is not None and message_id is not None:
                remember(reply.remember, reply.chat_id, message_id, reply.kind)
        except TelegramError as error:
            log.warning("could not message chat %s: %s", reply.chat_id, error)
    return sent


class Running:
    """A file that exists while the bot runs.

    Written at start and removed at a clean stop, which is what launchd's
    SIGTERM gives on a restart, a logout or a shutdown. Found already there at
    start, the last run ended some other way, and the operators are told.
    """

    def __init__(self, path: Path | str):
        self.path = Path(path)

    def start(self, now: dt.datetime) -> str | None:
        """Mark this run; returns when the last one started, if it never stopped."""
        previous = self.path.read_text(encoding="utf-8").strip() if self.path.exists() else None
        self.path.write_text(f"{now:%Y-%m-%d %H:%M}", encoding="utf-8")
        return previous

    def stop(self) -> None:
        self.path.unlink(missing_ok=True)


def build(token: str, bot: Bot, running: Running | None = None) -> Application:
    async def remind(app: Application) -> None:
        """Ask the core every few minutes whether the daily reminder is due."""
        while True:
            await asyncio.sleep(REMIND_CHECK)
            try:
                replies = await asyncio.to_thread(bot.reminders, dt.datetime.now())
                if replies:
                    sent = await deliver(app.bot, replies, bot.remember)
                    log.info("queue reminder: %d of %d sent", sent, len(replies))
            except Exception:
                log.exception("the queue reminder failed")

    async def post_init(app: Application) -> None:
        app.bot_data["reminders"] = asyncio.get_running_loop().create_task(remind(app))
        if running is not None:
            since = running.start(dt.datetime.now())
            if since is not None:
                log.warning("the last run, started %s, did not stop cleanly", since)
                await deliver(app.bot, bot.restarted(since))

    async def post_shutdown(app: Application) -> None:
        task = app.bot_data.get("reminders")
        if task is not None:
            task.cancel()
        if running is not None:
            running.stop()

    app = (
        ApplicationBuilder()
        .token(token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    async def on_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        loop = asyncio.get_running_loop()

        def fetch(file_id: str) -> bytes:
            async def download() -> bytes:
                file = await context.bot.get_file(file_id)
                return bytes(await file.download_as_bytearray())

            # Called from the worker thread the core runs on.
            return asyncio.run_coroutine_threadsafe(download(), loop).result(DOWNLOAD_TIMEOUT)

        incoming = incoming_from(update, fetch)
        if incoming is None:
            return
        if update.callback_query is not None:
            # Stops the button's spinner; the answer itself is the edit.
            try:
                await update.callback_query.answer()
            except TelegramError:
                pass
        if incoming.private and incoming.button is None:
            # Reading a receipt or a typed message can take the model seconds.
            try:
                await context.bot.send_chat_action(incoming.chat_id, ChatAction.TYPING)
            except TelegramError:
                pass
        try:
            # The core blocks on Sheets, Vision and the model; keep it off the
            # event loop.
            replies = await asyncio.to_thread(bot.handle, incoming)
        except Exception as error:
            log.exception("handling an update from %s failed", incoming.user_id)
            replies = bot.failed(incoming, error)
        sent = await deliver(context.bot, replies, bot.remember)
        # Who, what kind and how many, never what: messages can name patients.
        kind = "button" if incoming.button else "photo" if incoming.photo else "text"
        log.info(
            "%s from %s (%s): %d of %d replies sent",
            kind,
            incoming.user_id,
            "private" if incoming.private else "group",
            sent,
            len(replies),
        )

    async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        log.error("handling an update failed", exc_info=context.error)

    app.add_handler(MessageHandler(filters.ALL, on_update))
    app.add_handler(CallbackQueryHandler(on_update))
    app.add_error_handler(on_error)
    return app


def run(token: str, bot: Bot, running: Running | None = None) -> None:
    app = build(token, bot, running)
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=False)
