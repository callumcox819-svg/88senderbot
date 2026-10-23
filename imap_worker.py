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


def _e(value: str) -> str:
    return escape(value or "", quote=False)


def _reply_preview(raw: str) -> str:
    """Новый ответ, затем -------- и процитированное письмо. Строку On/Am/Op wrote не показываем."""
    txt = (raw or "").replace("\r\n", "\n").replace("\r", "\n")
    markers = ("\nOn ", "\nAm ", "\nOp ", "\nLe ", "\n-----Original Message-----", "\nFrom:", "\nОт:")
    cut = None
    for marker in markers:
        pos = txt.find(marker)
        if pos != -1:
            cut = pos if cut is None else min(cut, pos)
    seller = txt if cut is None else txt[:cut]
    seller_lines = []
    for line in seller.split("\n"):
        if line.strip().startswith(">") and seller_lines:
            break
        seller_lines.append(line)
    seller = "\n".join(seller_lines).strip()
    quoted = ""
    if cut is not None:
        lines = txt[cut:].split("\n")
        start = 0
        for i, line in enumerate(lines):
            low = line.strip().lower()
            if not low:
                continue
            if any(word in low for word in ("wrote", "schrieb", "schreef", "a écrit", "original message")) or low.startswith(">"):
                start = i + 1 if not low.startswith(">") else i
                break
        buf = []
        for j in range(start, len(lines)):
            line = lines[j]
            low = line.strip().lower()
            if j != start and (low.startswith(("on ", "am ", "le ", "op ")) or "original message" in low or low.startswith("from:")):
                break
            if line.strip().startswith(">"):
                line = line.lstrip("> ").rstrip()
            if not line.strip() and buf:
                break
            buf.append(line)
        quoted = "\n".join(buf).strip()
    if quoted:
        return f"{seller}\n\n--------\n{quoted}"
    return seller


def _card(title, mailbox, sender_name, sender_mail, subject, body) -> str:
    shown = _e(_reply_preview(body)[:3200] or "—")
    return (
        f"⚡️ Получено сообщение на \"<b>{_e(title)}</b>\"\n"
        f"<code>{_e(mailbox)}</code>\n"
        f"от \"<b>{_e(sender_name)}</b>\" <code>{_e(sender_mail)}</code>\n\n"
        f"<b>Тема:</b>\n<blockquote><code>{_e(subject or '—')}</code></blockquote>\n\n"
        f"<b>Текст:</b>\n<blockquote expandable><code>{shown}</code></blockquote>"
    )


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
                    text = _card(title, account["email"], sender_name, sender_mail, subject, body)
                    kb = None
                    if letter["from"]:
                        kb = InlineKeyboardMarkup(
                            [[InlineKeyboardButton("Написать ещё", callback_data=f"write:{inbox_id}")]]
                        )
                    anchor = db.first_inbox_message(account["id"], letter["from"])
                    kwargs = {"parse_mode": "HTML", "reply_markup": kb}
                    if anchor:
                        kwargs["reply_to_message_id"] = anchor
                    try:
                        sent = await bot.send_message(ADMIN_ID, text, **kwargs)
                    except Exception:
                        if not anchor:
                            raise
                        kwargs.pop("reply_to_message_id", None)
                        sent = await bot.send_message(ADMIN_ID, text, **kwargs)
                    db.set_inbox_message(inbox_id, sent.message_id)
            except Exception:
                log.exception("imap %s", account["email"])
        await asyncio.sleep(45)


if __name__ == "__main__":
    asyncio.run(loop())
