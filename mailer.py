import imaplib
import smtplib
import ssl
from email.message import EmailMessage
from email.header import decode_header
from email.utils import parseaddr


GMAIL = ("smtp.gmail.com", 587, "imap.gmail.com", 993)


def gmail_hosts(email: str) -> tuple[str, int, str, int] | None:
    domain = email.split("@", 1)[-1].lower()
    if domain in ("gmail.com", "googlemail.com"):
        return GMAIL
    return None


def send_mail(account, to_addr: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = account["email"]
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body)

    context = ssl.create_default_context()
    with smtplib.SMTP(account["smtp_host"], account["smtp_port"], timeout=30) as smtp:
        smtp.ehlo()
        smtp.starttls(context=context)
        smtp.ehlo()
        smtp.login(account["email"], account["password"])
        smtp.send_message(msg)


def _decode(value: str | None) -> str:
    if not value:
        return ""
    parts = []
    for chunk, enc in decode_header(value):
        if isinstance(chunk, bytes):
            parts.append(chunk.decode(enc or "utf-8", errors="replace"))
        else:
            parts.append(chunk)
    return "".join(parts)


def fetch_new(account) -> tuple[int, list[dict]]:
    context = ssl.create_default_context()
    imap = imaplib.IMAP4_SSL(account["imap_host"], account["imap_port"], ssl_context=context)
    try:
        imap.login(account["email"], account["password"])
        imap.select("INBOX")
        status, data = imap.uid("search", None, "ALL")
        if status != "OK" or not data or not data[0]:
            return account["last_uid"], []
        uids = [int(x) for x in data[0].split()]
        last = account["last_uid"]
        if last == 0:
            return (max(uids) if uids else 0), []
        fresh = [u for u in uids if u > last]
        letters = []
        for uid in fresh[-10:]:
            status, fetched = imap.uid("fetch", str(uid), "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)] BODY.PEEK[TEXT])")
            if status != "OK" or not fetched:
                continue
            raw = b""
            for item in fetched:
                if isinstance(item, tuple):
                    raw += item[1]
            text = raw.decode("utf-8", errors="replace")
            header, _, body = text.partition("\r\n\r\n")
            if not body:
                header, _, body = text.partition("\n\n")
            sender = ""
            subject = ""
            for line in header.splitlines():
                low = line.lower()
                if low.startswith("from:"):
                    sender = parseaddr(_decode(line.split(":", 1)[1].strip()))[1] or _decode(line.split(":", 1)[1].strip())
                elif low.startswith("subject:"):
                    subject = _decode(line.split(":", 1)[1].strip())
            letters.append({"uid": uid, "from": sender, "subject": subject, "body": body.strip()[:3500]})
        new_last = max(uids) if uids else last
        return new_last, letters
    finally:
        try:
            imap.logout()
        except Exception:
            pass
