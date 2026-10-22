import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).with_name("mailer.db")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
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
            """
        )


def add_account(email, password, smtp_host, smtp_port, imap_host, imap_port) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO accounts (email, password, smtp_host, smtp_port, imap_host, imap_port)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(email) DO UPDATE SET
                password=excluded.password,
                smtp_host=excluded.smtp_host,
                smtp_port=excluded.smtp_port,
                imap_host=excluded.imap_host,
                imap_port=excluded.imap_port
            """,
            (email, password, smtp_host, smtp_port, imap_host, imap_port),
        )


def list_accounts():
    with connect() as conn:
        return conn.execute("SELECT * FROM accounts ORDER BY id").fetchall()


def get_account(account_id: int):
    with connect() as conn:
        return conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()


def delete_account(account_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM accounts WHERE id=?", (account_id,))


def set_last_uid(account_id: int, uid: int) -> None:
    with connect() as conn:
        conn.execute("UPDATE accounts SET last_uid=? WHERE id=?", (uid, account_id))


def add_preset(subject: str, body: str) -> None:
    with connect() as conn:
        conn.execute("INSERT INTO presets (subject, body) VALUES (?, ?)", (subject, body))


def list_presets():
    with connect() as conn:
        return conn.execute("SELECT * FROM presets ORDER BY id").fetchall()


def delete_preset(preset_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM presets WHERE id=?", (preset_id,))


def add_reply(title: str, body: str) -> None:
    with connect() as conn:
        conn.execute("INSERT INTO replies (title, body) VALUES (?, ?)", (title, body))


def list_replies():
    with connect() as conn:
        return conn.execute("SELECT * FROM replies ORDER BY id").fetchall()


def get_reply(reply_id: int):
    with connect() as conn:
        return conn.execute("SELECT * FROM replies WHERE id=?", (reply_id,)).fetchone()


def delete_reply(reply_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM replies WHERE id=?", (reply_id,))


def save_inbox(account_id: int, sender: str, subject: str, body: str) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO inbox (account_id, sender, subject, body) VALUES (?, ?, ?, ?)",
            (account_id, sender, subject, body),
        )
        return cur.lastrowid


def get_inbox(inbox_id: int):
    with connect() as conn:
        return conn.execute("SELECT * FROM inbox WHERE id=?", (inbox_id,)).fetchone()
