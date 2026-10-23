import asyncio
import logging
import os

from dotenv import load_dotenv
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, MessageEntity

import db
import mailer

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("imap")

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = int(os.environ["ADMIN_ID"])


def _u16(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _card(title, mailbox, sender_name, sender_mail, subject, body):
    chunks = [
        f"⚡️ Получено сообщение на \"{title}\"\n",
        f"{mailbox}\n",
        f"от \"{sender_name}\" {sender_mail}\n\n",
        "Тема:\n",
        subject,
        "\nТекст:\n",
        body,
    ]
    text = "".join(chunks)
    if _u16(text) > 4000:
        text = text.encode("utf-16-le")[:8000].decode("utf-16-le", errors="ignore")
        body = text[text.rfind("\nТекст:\n") + len("\nТекст:\n"):]
        subject_at = text.find("Тема:\n") + len("Тема:\n")
        subject = text[subject_at:text.find("\nТекст:\n")]
        chunks = [
            f"⚡️ Получено сообщение на \"{title}\"\n",
            f"{mailbox}\n",
            f"от \"{sender_name}\" {sender_mail}\n\n",
            "Тема:\n",
            subject,
            "\nТекст:\n",
            body,
        ]
        text = "".join(chunks)
    entities = []
    for chunk in (subject, body):
        if not chunk:
            continue
        entities.append(
            MessageEntity(
                MessageEntity.EXPANDABLE_BLOCKQUOTE,
                _u16_offset(chunks, chunk),
                _u16(chunk),
            )
        )
    return text, entities


def _u16_offset(chunks, target) -> int:
    total = 0
    for chunk in chunks:
        if chunk is target:
            return total
        total += _u16(chunk)
    return total


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
                    own_name = (db.get_setting("sender_name") or account["display_name"] or "").strip()
                    title = f"{sender_name} ({own_name})" if own_name else sender_name
                    subject = (letter["subject"] or "(без темы)").strip()
                    body = (letter["body"] or "(пусто)").strip()
                    text, entities = _card(title, account["email"], sender_name, sender_mail, subject, body)
                    kb = None
                    if letter["from"]:
                        kb = InlineKeyboardMarkup(
                            [[InlineKeyboardButton("Написать ещё", callback_data=f"write:{inbox_id}")]]
                        )
                    sent = await bot.send_message(
                        ADMIN_ID, text, entities=entities, reply_markup=kb
                    )
                    db.set_inbox_message(inbox_id, sent.message_id)
            except Exception:
                log.exception("imap %s", account["email"])
        await asyncio.sleep(45)


if __name__ == "__main__":
    asyncio.run(loop())
