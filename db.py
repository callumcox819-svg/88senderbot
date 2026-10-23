import os
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).with_name("mailer.db")
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()


def _pg():
    return bool(DATABASE_URL)


def connect():
    if _pg():
        import psycopg
        from psycopg.rows import dict_row

        url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
        return psycopg.connect(url, row_factory=dict_row)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _q(sql: str) -> str:
    if _pg():
        return sql.replace("?", "%s")
    return sql


def _exec(sql: str, params=(), fetch=None):
    conn = connect()
    try:
        cur = conn.execute(_q(sql), params)
        if fetch == "all":
            rows = cur.fetchall()
        elif fetch == "one":
            rows = cur.fetchone()
        elif fetch == "id":
            rows = cur.fetchone()
            rows = rows["id"] if isinstance(rows, dict) else rows[0]
        else:
            rows = None
        conn.commit()
        return rows
    finally:
        conn.close()


def init() -> None:
    if _pg():
        statements = [
            """
            CREATE TABLE IF NOT EXISTS accounts (
                id SERIAL PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                smtp_host TEXT NOT NULL,
                smtp_port INTEGER NOT NULL,
                imap_host TEXT NOT NULL,
                imap_port INTEGER NOT NULL,
                last_uid INTEGER NOT NULL DEFAULT 0
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS presets (
                id SERIAL PRIMARY KEY,
                subject TEXT NOT NULL,
                body TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS replies (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                body TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS inbox (
                id SERIAL PRIMARY KEY,
                account_id INTEGER NOT NULL,
                sender TEXT NOT NULL,
                subject TEXT NOT NULL,
                body TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS proxies (
                id SERIAL PRIMARY KEY,
                raw TEXT NOT NULL,
                kind TEXT NOT NULL,
                host TEXT NOT NULL,
                port INTEGER NOT NULL,
                username TEXT,
                password TEXT,
                active INTEGER NOT NULL DEFAULT 0
            )
            """,
        ]
        conn = connect()
        try:
            for statement in statements:
                conn.execute(statement)
            conn.execute("ALTER TABLE accounts ADD COLUMN IF NOT EXISTS display_name TEXT NOT NULL DEFAULT ''")
            conn.execute("ALTER TABLE inbox ADD COLUMN IF NOT EXISTS tg_message_id BIGINT")
            conn.execute("CREATE TABLE IF NOT EXISTS sent_to (email TEXT PRIMARY KEY)")
            conn.execute("ALTER TABLE sent_to ADD COLUMN IF NOT EXISTS offer TEXT NOT NULL DEFAULT ''")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            conn.commit()
        finally:
            conn.close()
        return

    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                smtp_host TEXT NOT NULL,
                smtp_port INTEGER NOT NULL,
                imap_host TEXT NOT NULL,
                imap_port INTEGER NOT NULL,
                last_uid INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS presets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT NOT NULL,
                body TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS replies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                body TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS inbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                sender TEXT NOT NULL,
                subject TEXT NOT NULL,
                body TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS proxies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                raw TEXT NOT NULL,
                kind TEXT NOT NULL,
                host TEXT NOT NULL,
                port INTEGER NOT NULL,
                username TEXT,
                password TEXT,
                active INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sent_to (
                email TEXT PRIMARY KEY
            );
            """
        )
        try:
            conn.execute("ALTER TABLE accounts ADD COLUMN display_name TEXT NOT NULL DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE inbox ADD COLUMN tg_message_id INTEGER")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE sent_to ADD COLUMN offer TEXT NOT NULL DEFAULT ''")
        except sqlite3.OperationalError:
            pass


def add_account(email, password, smtp_host, smtp_port, imap_host, imap_port, display_name="") -> None:
    _exec(
        """
        INSERT INTO accounts (email, password, smtp_host, smtp_port, imap_host, imap_port, display_name)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(email) DO UPDATE SET
            password=excluded.password,
            smtp_host=excluded.smtp_host,
            smtp_port=excluded.smtp_port,
            imap_host=excluded.imap_host,
            imap_port=excluded.imap_port,
            display_name=CASE
                WHEN excluded.display_name <> '' THEN excluded.display_name
                ELSE accounts.display_name
            END
        """,
        (email, password, smtp_host, smtp_port, imap_host, imap_port, display_name),
    )


def set_display_name(account_id: int, display_name: str) -> None:
    _exec("UPDATE accounts SET display_name=? WHERE id=?", (display_name, account_id))


def get_setting(key: str, default: str = "") -> str:
    row = _exec("SELECT value FROM settings WHERE key=?", (key,), fetch="one")
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    _exec(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def list_accounts():
    return _exec("SELECT * FROM accounts ORDER BY id", fetch="all")


def get_account(account_id: int):
    return _exec("SELECT * FROM accounts WHERE id=?", (account_id,), fetch="one")


def delete_account(account_id: int) -> None:
    _exec("DELETE FROM accounts WHERE id=?", (account_id,))


def set_last_uid(account_id: int, uid: int) -> None:
    _exec("UPDATE accounts SET last_uid=? WHERE id=?", (uid, account_id))


def add_preset(subject: str, body: str) -> None:
    _exec("INSERT INTO presets (subject, body) VALUES (?, ?)", (subject, body))


def list_presets():
    return _exec("SELECT * FROM presets ORDER BY id", fetch="all")


def delete_preset(preset_id: int) -> None:
    _exec("DELETE FROM presets WHERE id=?", (preset_id,))


def add_reply(title: str, body: str) -> None:
    _exec("INSERT INTO replies (title, body) VALUES (?, ?)", (title, body))


def list_replies():
    return _exec("SELECT * FROM replies ORDER BY id", fetch="all")


def get_reply(reply_id: int):
    return _exec("SELECT * FROM replies WHERE id=?", (reply_id,), fetch="one")


def delete_reply(reply_id: int) -> None:
    _exec("DELETE FROM replies WHERE id=?", (reply_id,))


def save_inbox(account_id: int, sender: str, subject: str, body: str) -> int:
    return _exec(
        "INSERT INTO inbox (account_id, sender, subject, body) VALUES (?, ?, ?, ?) RETURNING id",
        (account_id, sender, subject, body),
        fetch="id",
    )


def get_inbox(inbox_id: int):
    return _exec("SELECT * FROM inbox WHERE id=?", (inbox_id,), fetch="one")


def set_inbox_message(inbox_id: int, message_id: int) -> None:
    _exec("UPDATE inbox SET tg_message_id=? WHERE id=?", (message_id, inbox_id))


def remember_sent(email: str, offer: str = "") -> None:
    email = (email or "").strip().lower()
    offer = (offer or "").strip()
    if not email:
        return
    _exec(
        """
        INSERT INTO sent_to (email, offer) VALUES (?, ?)
        ON CONFLICT(email) DO UPDATE SET
            offer=CASE WHEN excluded.offer <> '' THEN excluded.offer ELSE sent_to.offer END
        """,
        (email, offer),
    )


def sent_offer(email: str) -> str:
    email = (email or "").strip().lower()
    if not email:
        return ""
    row = _exec("SELECT offer FROM sent_to WHERE email=?", (email,), fetch="one")
    if not row:
        return ""
    return (row["offer"] or "").strip()


def was_sent_to(email: str) -> bool:
    email = (email or "").strip().lower()
    if not email:
        return False
    return bool(_exec("SELECT email FROM sent_to WHERE email=?", (email,), fetch="one"))


def first_inbox_message(account_id: int, sender: str):
    row = _exec(
        """
        SELECT tg_message_id FROM inbox
        WHERE account_id=? AND lower(sender)=lower(?) AND tg_message_id IS NOT NULL
        ORDER BY id LIMIT 1
        """,
        (account_id, sender),
        fetch="one",
    )
    return row["tg_message_id"] if row else None


def add_proxy(raw, kind, host, port, username, password) -> None:
    _exec("UPDATE proxies SET active=0")
    _exec(
        """
        INSERT INTO proxies (raw, kind, host, port, username, password, active)
        VALUES (?, ?, ?, ?, ?, ?, 1)
        """,
        (raw, kind, host, port, username, password),
    )


def list_proxies():
    return _exec("SELECT * FROM proxies ORDER BY id", fetch="all")


def get_proxy(proxy_id: int):
    return _exec("SELECT * FROM proxies WHERE id=?", (proxy_id,), fetch="one")


def get_active_proxy():
    return _exec("SELECT * FROM proxies WHERE active=1 ORDER BY id DESC", fetch="one")


def activate_proxy(proxy_id: int) -> None:
    _exec("UPDATE proxies SET active=0")
    _exec("UPDATE proxies SET active=1 WHERE id=?", (proxy_id,))


def delete_proxy(proxy_id: int) -> None:
    _exec("DELETE FROM proxies WHERE id=?", (proxy_id,))
