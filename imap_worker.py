import asyncio
import logging
import os

from dotenv import load_dotenv
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

import db
import mailer

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("imap")

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = int(os.environ["ADMIN_ID"])


async def loop():
    db.init()
    bot = Bot(BOT_TOKEN)
    while True:
        for account in db.list_accounts():
            try:
                new_uid, letters = await asyncio.to_thread(mailer.fetch_new, account, db.get_active_proxy())
                if new_uid != account["last_uid"]:
                    db.set_last_uid(account["id"], new_uid)
                for letter in letters:
                    inbox_id = db.save_inbox(account["id"], letter["from"], letter["subject"], letter["body"])
                    text = (
                        f"Получено сообщение на {account['email']}\n"
                        f"от {letter['from'] or 'неизвестного адреса'}\n\n"
                        f"Тема:\n{letter['subject'] or '(без темы)'}\n\n"
                        f"Текст:\n{letter['body'] or '(пусто)'}"
                    )
                    kb = None
                    if letter["from"]:
                        kb = InlineKeyboardMarkup(
                            [[InlineKeyboardButton("Написать ещё", callback_data=f"write:{inbox_id}")]]
                        )
                    await bot.send_message(ADMIN_ID, text[:4000], reply_markup=kb)
            except Exception:
                log.exception("imap %s", account["email"])
        await asyncio.sleep(45)


if __name__ == "__main__":
    asyncio.run(loop())
