import imaplib
import re
import smtplib
import time
import socket
import ssl
import threading
from contextlib import contextmanager
from email import message_from_bytes
from email.message import EmailMessage
from html import unescape

import socks
from email.header import decode_header
from email.utils import formataddr, parseaddr


GMAIL = ("smtp.gmail.com", 587, "imap.gmail.com", 993)


def gmail_hosts(email: str) -> tuple[str, int, str, int] | None:
    domain = email.split("@", 1)[-1].lower()
    if domain in ("gmail.com", "googlemail.com"):
        return GMAIL
    return None


_ORIG_SOCKET = socket.socket
_PROXY_LOCK = threading.Lock()


def parse_proxy(raw: str) -> dict:
    text = raw.strip()
    kind = "socks5"
    lowered = text.lower()
    for prefix, name in (("socks5://", "socks5"), ("socks4://", "socks4"), ("http://", "http")):
        if lowered.startswith(prefix):
            kind = name
            text = text[len(prefix):]
            break
    username = password = None
    if "@" in text:
        auth, text = text.rsplit("@", 1)
        username, _, password = auth.partition(":")
    parts = text.split(":")
    if len(parts) == 4 and username is None:
        host, port, username, password = parts
    elif len(parts) == 2:
        host, port = parts
    else:
        raise ValueError("Формат: host:port, host:port:user:pass или socks5://user:pass@host:port")
    return {
        "kind": kind,
        "host": host.strip(),
        "port": int(port),
        "username": username or None,
        "password": password or None,
    }


def _socks_kind(name: str):
    return {"socks5": socks.SOCKS5, "socks4": socks.SOCKS4, "http": socks.HTTP}[name]


@contextmanager
def via_proxy(proxy):
    if not proxy:
        yield
        return
    with _PROXY_LOCK:
        socks.set_default_proxy(
            _socks_kind(proxy["kind"]),
            proxy["host"],
            int(proxy["port"]),
            username=proxy["username"] or None,
            password=proxy["password"] or None,
        )
        socket.socket = socks.socksocket
        try:
            yield
        finally:
            socks.set_default_proxy()
            socket.socket = _ORIG_SOCKET


def check_proxy(proxy) -> None:
    with via_proxy(proxy):
        sock = socket.create_connection(("smtp.gmail.com", 587), timeout=15)
        sock.close()


def _socks_connection(proxy, dest, timeout):
    return socks.create_connection(
        dest,
        timeout=timeout,
        proxy_type=_socks_kind(proxy["kind"]),
        proxy_addr=proxy["host"],
        proxy_port=int(proxy["port"]),
        proxy_username=proxy.get("username") or None,
        proxy_password=proxy.get("password") or None,
        proxy_rdns=True,
    )


class _ProxySMTP(smtplib.SMTP_SSL):
    def __init__(self, host, proxy, timeout=25, context=None):
        self._proxy = proxy
        super().__init__(host, 465, timeout=timeout, context=context)

    def _get_socket(self, host, port, timeout):
        raw = _socks_connection(self._proxy, (host, port), timeout)
        return self.context.wrap_socket(raw, server_hostname=host)


class _ProxySMTPStartTLS(smtplib.SMTP):
    def __init__(self, host, proxy, timeout=25):
        self._proxy = proxy
        super().__init__(host, 587, timeout=timeout)

    def _get_socket(self, host, port, timeout):
        return _socks_connection(self._proxy, (host, port), timeout)


def _deliver(account, msg, proxy, context) -> None:
    try:
        with _ProxySMTP(account["smtp_host"], proxy, context=context) as smtp:
            smtp.login(account["email"], account["password"])
            smtp.send_message(msg)
        return
    except Exception:
        pass
    with _ProxySMTPStartTLS(account["smtp_host"], proxy) as smtp:
        smtp.ehlo()
        smtp.starttls(context=context)
        smtp.ehlo()
        smtp.login(account["email"], account["password"])
        smtp.send_message(msg)


def send_mail(account, to_addr: str, subject: str, body: str, proxy=None, sender_name=None) -> None:
    if not proxy:
        raise RuntimeError("Нет активного прокси. Письмо не отправлено.")
    msg = EmailMessage()
    sender_name = (sender_name if sender_name is not None else account["display_name"] or "").strip()
    msg["From"] = formataddr((sender_name, account["email"])) if sender_name else account["email"]
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body)

    context = ssl.create_default_context()
    last_error = None
    for attempt in range(3):
        try:
            _deliver(account, msg, proxy, context)
            return
        except Exception as exc:
            last_error = exc
            time.sleep(2)
    raise RuntimeError(f"Прокси оборвал соединение 3 раза: {last_error}")


def _html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>", "\n", html)
    html = re.sub(r"(?i)</p>", "\n", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    text = unescape(html)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _new_part(text: str) -> str:
    kept = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(">"):
            continue
        if re.match(r"(?i)^wrote:$", stripped):
            break
        if re.match(r"(?i)^on .+wrote:?$", stripped) or re.match(r"(?i)^on .+\d{4}", stripped):
            break
        if stripped.startswith("-----") or re.match(r"^_{5,}$", stripped):
            break
        kept.append(line.rstrip())
    return "\n".join(kept).strip()


def _plain(msg) -> str:
    if msg.is_multipart():
        plain = ""
        html = ""
        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            if "attachment" in (part.get("Content-Disposition") or "").lower():
                continue
            payload = part.get_payload(decode=True) or b""
            charset = part.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
            if part.get_content_type() == "text/plain" and not plain:
                plain = text
            elif part.get_content_type() == "text/html" and not html:
                html = text
        return _new_part(plain or _html_to_text(html))
    payload = msg.get_payload(decode=True) or b""
    text = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
    if msg.get_content_type() == "text/html":
        return _new_part(_html_to_text(text))
    return _new_part(text)


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


def fetch_new(account, proxy=None) -> tuple[int, list[dict]]:
    if not proxy:
        raise RuntimeError("Нет активного прокси. IMAP не подключается напрямую.")
    context = ssl.create_default_context()
    with via_proxy(proxy):
        return _fetch_new(account, context)


def _fetch_new(account, context) -> tuple[int, list[dict]]:
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
        handled = last
        for uid in fresh[:15]:
            status, fetched = imap.uid("fetch", str(uid), "(BODY.PEEK[])")
            if status != "OK" or not fetched:
                break
            raw = next((item[1] for item in fetched if isinstance(item, tuple)), b"")
            if not raw:
                break
            msg = message_from_bytes(raw)
            name, email = parseaddr(_decode(msg.get("From")))
            letters.append(
                {
                    "uid": uid,
                    "from": email or name,
                    "name": name,
                    "subject": _decode(msg.get("Subject")),
                    "body": _plain(msg)[:3500],
                    "mid": (msg.get("Message-ID") or "").strip().strip("<>").split("@")[0],
                }
            )
            handled = uid
        return handled, letters
    finally:
        try:
            imap.logout()
        except Exception:
            pass
