import asyncio
import logging
import os
import random
import re

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import db
import mailer

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("mailbot")

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = int(os.environ["ADMIN_ID"])

(
    ADD_ACCOUNT,
    ADD_PRESET_SUBJECT,
    ADD_PRESET_BODY,
    ADD_REPLY_TITLE,
    ADD_REPLY_BODY,
    SEND_TO,
    SEND_OFFER,
    REPLY_OFFER,
    REPLY_MANUAL,
    ADD_PROXY,
    SET_NAME,
) = range(11)

def main_menu():
    current = db.get_setting("sender_name").strip()
    label = f"ИМЯ ОТПРАВИТЕЛЯ: {current}" if current else "ИМЯ ОТПРАВИТЕЛЯ"
    subject = db.get_setting("mail_subject").strip()
    subject_label = f"Тема письма: {subject[:40]}" if subject else "Тема письма"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Аккаунты", callback_data="accounts")],
            [InlineKeyboardButton("Умные пресеты", callback_data="presets")],
            [InlineKeyboardButton("Пресеты", callback_data="replies")],
            [InlineKeyboardButton("Прокси", callback_data="proxies")],
            [InlineKeyboardButton(label, callback_data="sender_name")],
            [InlineKeyboardButton(subject_label, callback_data="mail_subject")],
            [InlineKeyboardButton("Отправить письмо", callback_data="send")],
        ]
    )


def proxy_keyboard():
    rows = db.list_proxies() or []
    kb = []
    for row in rows:
        mark = "● " if row["active"] else ""
        kb.append([InlineKeyboardButton(f"{mark}{row['host']}:{row['port']}", callback_data=f"px_use:{row['id']}")])
        kb.append(
            [
                InlineKeyboardButton("Проверить", callback_data=f"px_check:{row['id']}"),
                InlineKeyboardButton("Удалить", callback_data=f"px_del:{row['id']}"),
            ]
        )
    kb.append([InlineKeyboardButton("Добавить прокси", callback_data="px_add")])
    kb.append([InlineKeyboardButton("Назад", callback_data="home")])
    text = "Прокси нет." if not rows else "Список прокси. Точка — тот, через который идёт почта."
    return text, InlineKeyboardMarkup(kb)


def only_admin(update: Update) -> bool:
    user = update.effective_user
    return bool(user and user.id == ADMIN_ID)


def apply_offer(text: str, offer: str) -> str:
    return re.sub(r"OFFER", offer, text)


def from_name():
    return db.get_setting("sender_name").strip() or None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not only_admin(update):
        return
    await update.effective_message.reply_text(
        "Почта в боте. Письмо уходит только туда, куда ты введёшь адрес вручную.",
        reply_markup=main_menu(),
    )
    return ConversationHandler.END


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not only_admin(update):
        return ConversationHandler.END
    data = query.data
    if data == "home":
        await query.edit_message_text("Меню.", reply_markup=main_menu())
        return ConversationHandler.END
    if data == "accounts":
        rows = db.list_accounts()
        lines = []
        kb = [[InlineKeyboardButton("Добавить логин:пароль", callback_data="acc_add")]]
        for row in rows:
            name = (row["display_name"] or "").strip() or "имя не задано"
            lines.append(f"{row['id']}. {row['email']} — {name}")
            kb.append([InlineKeyboardButton(f"Имя: {row['email']}", callback_data=f"acc_name:{row['id']}")])
            kb.append([InlineKeyboardButton(f"Удалить {row['email']}", callback_data=f"acc_del:{row['id']}")])
        kb.append([InlineKeyboardButton("Назад", callback_data="home")])
        await query.edit_message_text(
            "Аккаунты:\n" + ("\n".join(lines) if lines else "Пока пусто."),
            reply_markup=InlineKeyboardMarkup(kb),
        )
        return ConversationHandler.END
    if data == "presets":
        rows = db.list_presets()
        lines = []
        for r in rows:
            preview = " ".join((r["body"] or "").split())[:60]
            lines.append(f"{r['id']}. {preview}")
        kb = [
            [InlineKeyboardButton("Новый пресет", callback_data="pre_add")],
            *[[InlineKeyboardButton(f"Удалить #{r['id']}", callback_data=f"pre_del:{r['id']}")] for r in rows],
            [InlineKeyboardButton("Назад", callback_data="home")],
        ]
        head = "Умные пресеты. При отправке бот сам выбирает один.\n" if rows else "Умные пресеты:\n"
        await query.edit_message_text(head + ("\n".join(lines) if lines else "Пока пусто."), reply_markup=InlineKeyboardMarkup(kb))
        return ConversationHandler.END
    if data == "send":
        if not db.list_accounts():
            await query.edit_message_text("Сначала добавь почту.", reply_markup=main_menu())
            return ConversationHandler.END
        if not db.list_presets():
            await query.edit_message_text("Сначала добавь пресет.", reply_markup=main_menu())
            return ConversationHandler.END
        accounts = db.list_accounts()
        kb = [[InlineKeyboardButton(r["email"], callback_data=f"acc_pick:{r['id']}")] for r in accounts]
        kb.append([InlineKeyboardButton("Назад", callback_data="home")])
        await query.edit_message_text("С какого ящика отправить?", reply_markup=InlineKeyboardMarkup(kb))
        return ConversationHandler.END
    if data.startswith("acc_del:"):
        db.delete_account(int(data.split(":")[1]))
        await query.edit_message_text("Аккаунт удалён.", reply_markup=main_menu())
        return ConversationHandler.END
    if data.startswith("pre_del:"):
        db.delete_preset(int(data.split(":")[1]))
        await query.edit_message_text("Пресет удалён.", reply_markup=main_menu())
        return ConversationHandler.END
    if data == "replies":
        rows = db.list_replies()
        lines = [f"{r['id']}. {r['title']}" for r in rows] or ["Пока пусто."]
        kb = [
            [InlineKeyboardButton("Новый пресет ответа", callback_data="rep_add")],
            *[[InlineKeyboardButton(f"Удалить #{r['id']} {r['title']}", callback_data=f"rep_del:{r['id']}")] for r in rows],
            [InlineKeyboardButton("Назад", callback_data="home")],
        ]
        await query.edit_message_text(
            "Пресеты ответа продавцу:\n" + "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(kb),
        )
        return ConversationHandler.END
    if data.startswith("rep_del:"):
        db.delete_reply(int(data.split(":")[1]))
        await query.edit_message_text("Пресет ответа удалён.", reply_markup=main_menu())
        return ConversationHandler.END
    if data == "rep_add":
        await query.edit_message_text("Название кнопки. Например: Ещё продаётся")
        return ADD_REPLY_TITLE
    if data.startswith("write:"):
        inbox_id = int(data.split(":")[1])
        letter = db.get_inbox(inbox_id)
        if not letter:
            await query.edit_message_text("Письмо уже не найдено.", reply_markup=main_menu())
            return ConversationHandler.END
        rows = db.list_replies()
        kb = [[InlineKeyboardButton(r["title"], callback_data=f"use_rep:{inbox_id}:{r['id']}")] for r in rows]
        kb.append([InlineKeyboardButton("Написать вручную", callback_data=f"manual:{inbox_id}")])
        await query.edit_message_text(
            f"Ответ для {letter['sender']}\nВыбери шаблон или напиши текст сам.",
            reply_markup=InlineKeyboardMarkup(kb),
        )
        return ConversationHandler.END
    if data.startswith("manual:"):
        inbox_id = int(data.split(":")[1])
        letter = db.get_inbox(inbox_id)
        if not letter:
            await query.edit_message_text("Письмо уже не найдено.", reply_markup=main_menu())
            return ConversationHandler.END
        context.user_data["reply_inbox_id"] = inbox_id
        await query.edit_message_text(f"Напиши текст ответа для {letter['sender']}. Он уйдёт как есть.")
        return REPLY_MANUAL
    if data.startswith("use_rep:"):
        _, inbox_id, reply_id = data.split(":")
        letter = db.get_inbox(int(inbox_id))
        reply = db.get_reply(int(reply_id))
        if not letter or not reply:
            await query.edit_message_text("Письмо или пресет уже не найдены.", reply_markup=main_menu())
            return ConversationHandler.END
        context.user_data["reply_inbox_id"] = letter["id"]
        context.user_data["reply_id"] = reply["id"]
        if "OFFER" in reply["body"]:
            await query.edit_message_text("ВВЕДИТЕ НАЗВАНИЕ ТОВАРА")
            return REPLY_OFFER
        try:
            await _send_reply(query.message, context, offer="")
        except Exception as exc:
            log.exception("reply failed")
            await query.message.reply_text(f"Ответ не ушёл: {exc}", reply_markup=main_menu())
        return ConversationHandler.END
    if data == "proxies":
        text, kb = proxy_keyboard()
        await query.edit_message_text(text, reply_markup=kb)
        return ConversationHandler.END
    if data == "px_add":
        await query.edit_message_text(
            "Пришли прокси. Перед сохранением проверю соединение с Gmail.\n"
            "Формат: host:port, host:port:user:pass или socks5://user:pass@host:port"
        )
        return ADD_PROXY
    if data.startswith("px_del:"):
        db.delete_proxy(int(data.split(":")[1]))
        text, kb = proxy_keyboard()
        await query.edit_message_text("Прокси удалён.\n\n" + text, reply_markup=kb)
        return ConversationHandler.END
    if data.startswith("px_use:"):
        db.activate_proxy(int(data.split(":")[1]))
        text, kb = proxy_keyboard()
        await query.edit_message_text(text, reply_markup=kb)
        return ConversationHandler.END
    if data.startswith("px_check:"):
        proxy = db.get_proxy(int(data.split(":")[1]))
        await query.edit_message_text(f"Проверяю {proxy['host']}:{proxy['port']}…")
        try:
            await asyncio.to_thread(mailer.check_proxy, proxy)
            note = "Прокси отвечает."
        except Exception as exc:
            note = f"Прокси не работает: {exc}"
        text, kb = proxy_keyboard()
        await query.edit_message_text(note + "\n\n" + text, reply_markup=kb)
        return ConversationHandler.END
    if data == "acc_add":
        await query.edit_message_text(
            "Пришли один ящик или несколько, каждый с новой строки:\n"
            "логин:пароль_приложения\n"
            "логин:пароль:Имя отправителя\n\n"
            "Общее имя для всех ящиков задаётся кнопкой «ИМЯ ОТПРАВИТЕЛЯ» в меню.\n"
            "Порты Gmail подставятся сами."
        )
        return ADD_ACCOUNT
    if data == "sender_name":
        context.user_data["name_account_id"] = None
        context.user_data["setting_key"] = "sender_name"
        current = db.get_setting("sender_name").strip() or "не задано"
        await query.edit_message_text(
            f"Сейчас: {current}\nПришли имя. Оно будет в поле «От» у писем с любого ящика."
        )
        return SET_NAME
    if data == "mail_subject":
        context.user_data["name_account_id"] = None
        context.user_data["setting_key"] = "mail_subject"
        current = db.get_setting("mail_subject").strip() or "название товара"
        await query.edit_message_text(
            f"Сейчас: {current}\nПришли тему. Она будет у каждого исходящего письма. OFFER заменится на название товара."
        )
        return SET_NAME
    if data.startswith("acc_name:"):
        context.user_data["name_account_id"] = int(data.split(":")[1])
        await query.edit_message_text("Напиши имя отправителя. Оно будет в поле «От» у писем с этого ящика.")
        return SET_NAME
    if data == "pre_add":
        await query.edit_message_text(
            "Пришли тексты, каждый вариант с новой строки.\n"
            "OFFER заменится на название товара.\n"
            "При отправке бот сам выберет одну строку."
        )
        return ADD_PRESET_BODY
    if data.startswith("acc_pick:"):
        context.user_data["account_id"] = int(data.split(":")[1])
        await query.edit_message_text("Введите электронную почту, куда отправить письмо.")
        return SEND_TO
    return ConversationHandler.END


async def on_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not only_admin(update):
        return ConversationHandler.END
    lines = [line.strip() for line in (update.message.text or "").splitlines() if line.strip()]
    added, failed = [], []
    for line in lines:
        email, sep, rest = line.partition(":")
        password, _, display_name = rest.partition(":")
        email, password, display_name = email.strip(), password.replace(" ", "").strip(), display_name.strip()
        hosts = mailer.gmail_hosts(email)
        if not sep or "@" not in email or not password or not hosts:
            failed.append(email or line)
            continue
        smtp_host, smtp_port, imap_host, imap_port = hosts
        db.add_account(email, password, smtp_host, smtp_port, imap_host, imap_port, display_name)
        added.append(email)
    if not added:
        await update.message.reply_text("Ни одной строки не разобрал. Формат: логин:пароль", reply_markup=main_menu())
        return ConversationHandler.END
    text = "Добавлены:\n" + "\n".join(added)
    if failed:
        text += "\n\nНе разобрал:\n" + "\n".join(failed)
    await update.message.reply_text(text, reply_markup=main_menu())
    return ConversationHandler.END


async def on_sender_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not only_admin(update):
        return ConversationHandler.END
    name = (update.message.text or "").strip()
    account_id = context.user_data.get("name_account_id")
    if account_id:
        db.set_display_name(account_id, name)
        await update.message.reply_text(f"Имя отправителя: {name}", reply_markup=main_menu())
        return ConversationHandler.END
    if context.user_data.get("setting_key") == "mail_subject":
        db.set_setting("mail_subject", name)
        await update.message.reply_text(f"Тема письма: {name}", reply_markup=main_menu())
        return ConversationHandler.END
    db.set_setting("sender_name", name)
    await update.message.reply_text(f"Имя отправителя: {name}", reply_markup=main_menu())
    return ConversationHandler.END


async def on_proxy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not only_admin(update):
        return ConversationHandler.END
    raw = (update.message.text or "").strip()
    try:
        parsed = mailer.parse_proxy(raw)
        await update.message.reply_text("Проверяю прокси…")
        await asyncio.to_thread(mailer.check_proxy, parsed)
    except Exception as exc:
        await update.message.reply_text(f"Не добавил: {exc}", reply_markup=main_menu())
        return ConversationHandler.END
    db.add_proxy(raw, parsed["kind"], parsed["host"], parsed["port"], parsed["username"], parsed["password"])
    await update.message.reply_text(
        f"Прокси {parsed['host']}:{parsed['port']} работает и теперь используется для почты.",
        reply_markup=main_menu(),
    )
    return ConversationHandler.END


async def on_reply_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not only_admin(update):
        return ConversationHandler.END
    context.user_data["reply_title"] = (update.message.text or "").strip()[:40]
    await update.message.reply_text("Текст ответа продавцу. Если нужно название товара, вставь OFFER.")
    return ADD_REPLY_BODY


async def on_reply_body(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not only_admin(update):
        return ConversationHandler.END
    db.add_reply(context.user_data["reply_title"], (update.message.text or "").strip())
    await update.message.reply_text("Пресет ответа сохранён. Его можно выбрать после кнопки «Написать».", reply_markup=main_menu())
    return ConversationHandler.END


async def _send_reply(message, context, offer: str):
    letter = db.get_inbox(context.user_data["reply_inbox_id"])
    reply = db.get_reply(context.user_data["reply_id"])
    account = db.get_account(letter["account_id"])
    subject = letter["subject"]
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"
    body = apply_offer(reply["body"], offer) if offer else reply["body"]
    await asyncio.to_thread(mailer.send_mail, account, letter["sender"], subject, body, db.get_active_proxy(), from_name())
    await message.reply_text(
        f"Ответ «{reply['title']}» ушёл с {account['email']} на {letter['sender']}",
        reply_markup=main_menu(),
    )


async def on_reply_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not only_admin(update):
        return ConversationHandler.END
    letter = db.get_inbox(context.user_data["reply_inbox_id"])
    account = db.get_account(letter["account_id"])
    subject = letter["subject"]
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"
    body = (update.message.text or "").strip()
    try:
        await asyncio.to_thread(mailer.send_mail, account, letter["sender"], subject, body, db.get_active_proxy(), from_name())
    except Exception as exc:
        log.exception("manual reply failed")
        await update.message.reply_text(f"Ответ не ушёл: {exc}", reply_markup=main_menu())
        return ConversationHandler.END
    await update.message.reply_text(
        f"Ручной ответ ушёл с {account['email']} на {letter['sender']}",
        reply_markup=main_menu(),
    )
    return ConversationHandler.END


async def on_reply_offer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not only_admin(update):
        return ConversationHandler.END
    try:
        await _send_reply(update.message, context, offer=(update.message.text or "").strip())
    except Exception as exc:
        log.exception("reply failed")
        await update.message.reply_text(f"Ответ не ушёл: {exc}", reply_markup=main_menu())
    return ConversationHandler.END


async def on_preset_body(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not only_admin(update):
        return ConversationHandler.END
    raw = update.message.text or ""
    if re.search(r"(?m)^---\s*$", raw):
        bodies = [part.strip() for part in re.split(r"(?m)^---\s*$", raw) if part.strip()]
    else:
        bodies = [line.strip() for line in raw.splitlines() if line.strip()]
    if not bodies:
        await update.message.reply_text("Текст пустой. Пришли варианты ещё раз.")
        return ADD_PRESET_BODY
    for body in bodies:
        db.add_preset("OFFER", body)
    await update.message.reply_text(
        f"Сохранено вариантов: {len(bodies)}. При отправке бот выберет один случайно.",
        reply_markup=main_menu(),
    )
    return ConversationHandler.END


async def on_send_to(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not only_admin(update):
        return ConversationHandler.END
    to_addr = (update.message.text or "").strip()
    if "@" not in to_addr or " " in to_addr:
        await update.message.reply_text("Это не похоже на один адрес. Введи email ещё раз.")
        return SEND_TO
    context.user_data["to"] = to_addr
    preset = random.choice(db.list_presets())
    context.user_data["preset_id"] = preset["id"]
    context.user_data["preset_subject"] = preset["subject"]
    context.user_data["preset_body"] = preset["body"]
    await update.message.reply_text(
        f"Выбран вариант #{preset['id']}.\n\nВВЕДИТЕ НАЗВАНИЕ ТОВАРА"
    )
    return SEND_OFFER


async def on_send_offer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not only_admin(update):
        return ConversationHandler.END
    offer = (update.message.text or "").strip()
    account = db.get_account(context.user_data["account_id"])
    subject_template = db.get_setting("mail_subject").strip() or context.user_data["preset_subject"]
    subject = apply_offer(subject_template, offer)
    body = apply_offer(context.user_data["preset_body"], offer)
    to_addr = context.user_data["to"]
    try:
        await asyncio.to_thread(mailer.send_mail, account, to_addr, subject, body, db.get_active_proxy(), from_name())
    except Exception as exc:
        log.exception("send failed")
        await update.message.reply_text(f"Не отправилось: {exc}", reply_markup=main_menu())
        return ConversationHandler.END
    await update.message.reply_text(
        f"Отправлено с {account['email']} на {to_addr}\nТема: {subject}",
        reply_markup=main_menu(),
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отменено.", reply_markup=main_menu())
    return ConversationHandler.END


def main():
    db.init()
    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CallbackQueryHandler(menu),
        ],
        states={
            ADD_ACCOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_account)],
            ADD_PRESET_BODY: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_preset_body)],
            ADD_REPLY_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_reply_title)],
            ADD_REPLY_BODY: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_reply_body)],
            SEND_TO: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_send_to)],
            SEND_OFFER: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_send_offer)],
            REPLY_OFFER: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_reply_offer)],
            REPLY_MANUAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_reply_manual)],
            ADD_PROXY: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_proxy)],
            SET_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_sender_name)],
        },
        fallbacks=[CommandHandler("cancel", cancel), CommandHandler("start", start)],
        per_message=False,
    )
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(conv)
    app.run_polling()


if __name__ == "__main__":
    main()
