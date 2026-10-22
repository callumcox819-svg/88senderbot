import asyncio
import logging
import os
from html import escape

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
                    if not db.was_sent_to(letter["from"]):
                        continue
                    inbox_id = db.save_inbox(account["id"], letter["from"], letter["subject"], letter["body"])
                    sender_name = letter.get("name") or letter["from"] or "неизвестного адреса"
                    sender_mail = letter["from"] or ""
                    own_name = (account["display_name"] or "").strip()
                    title = f"{sender_name} ({own_name})" if own_name else sender_name
                    lines = [
                        f"⚡️ Получено сообщение на \"{escape(title)}\"",
                        escape(account["email"]),
                        f"от \"{escape(sender_name)}\" {escape(sender_mail)}",
                        "",
                        "Тема:",
                        f"<blockquote expandable>{escape(letter['subject'] or '(без темы)')}</blockquote>",
                        "Текст:",
                        f"<blockquote expandable>{escape(letter['body'] or '(пусто)')}</blockquote>",
                    ]
                    text = "\n".join(lines)
                    kb = None
                    if letter["from"]:
                        kb = InlineKeyboardMarkup(
                            [[InlineKeyboardButton("Написать ещё", callback_data=f"write:{inbox_id}")]]
                        )
                    sent = await bot.send_message(ADMIN_ID, text[:4000], reply_markup=kb, parse_mode="HTML")
                    db.set_inbox_message(inbox_id, sent.message_id)
            except Exception:
                log.exception("imap %s", account["email"])
        await asyncio.sleep(45)


if __name__ == "__main__":
    asyncio.run(loop())
