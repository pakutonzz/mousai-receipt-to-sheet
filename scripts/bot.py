"""Run the Telegram bot.

    python scripts/bot.py

Long polling: the bot asks Telegram for new messages, so nothing here listens
for the outside world. Needs TELEGRAM_BOT_TOKEN in .env and a people file
(people.toml; copy people.example.toml to start).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    from mousai import describe, ocr, people, store, typed
    from mousai.bot.core import Bot
    from mousai.bot.polling import run
    from mousai.messages import english
    from mousai.review import Desk
    from mousai.sheets import Sheets, load_env

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # The HTTP client logs every long-poll request at INFO, which buries the
    # bot's own lines and puts the token-bearing URL in the log.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    env = load_env()
    token = env.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("TELEGRAM_BOT_TOKEN is not set in .env. Create the bot with @BotFather")
        print("and paste its token into .env on this machine.")
        return 1

    path = people.path_from_env(env)
    try:
        people_file = people.PeopleFile(path)
    except people.PeopleError as error:
        print(f"people file: {english(error.notice)}")
        return 1

    everyone = people_file.current().by_id.values()
    print("\n  mousai bot (long polling)")
    print(f"  people file   {path}")
    print(f"  keepers       {sum(p.is_keeper for p in everyone)}")
    print(f"  recorders     {sum(p.may_hand_in and not p.is_keeper for p in everyone)}")
    print(f"  operators     {sum(p.is_operator for p in everyone)}")

    # Sheets is opened on first use, so a missing credential shows up as a
    # Thai reply to whoever sent a receipt, not as a bot that will not start.
    sheets: list[Sheets] = []

    def get_sheets() -> Sheets:
        if not sheets:
            sheets.append(Sheets.from_env())
        return sheets[0]

    reader = ocr.detect(env)
    describer = describe.detect(env)
    interpreter = typed.detect(env)
    store_path = store.path_from_env(env)
    print(f"  store         {store_path}")
    print(f"  ocr           {reader.name}")
    print(f"  descriptions  {describer.name}")
    print(f"  typed text    {interpreter.name}")
    print()

    bot = Bot(
        people_file,
        desk=Desk(get_sheets),
        store=store.Store(store_path),
        reader=reader,
        describer=describer,
        interpreter=interpreter,
    )
    run(token, bot)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
