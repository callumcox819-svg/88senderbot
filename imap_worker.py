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
                    who = letter.get("name") or letter["from"] or "неизвестного адреса"
                    lines = [
                        f"Получено сообщение на {account['email']}",
                        f"от {who}",
                    ]
                    if letter.get("name") and letter["from"]:
                        lines.append(letter["from"])
                    lines += [
                        "",
                        "Тема:",
                        letter["subject"] or "(без темы)",
                        "",
                        "Текст:",
                        letter["body"] or "(пусто)",
                    ]
                    text = "\n".join(lines)
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
