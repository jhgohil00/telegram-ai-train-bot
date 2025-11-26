# db.py
import sqlite3
from datetime import datetime
from typing import Optional, Tuple, List

from config import Config


def get_connection():
    return sqlite3.connect(Config.DB_PATH)


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    # User profile (your gender, AI gender, interests)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS profiles (
            user_id INTEGER PRIMARY KEY,
            my_gender TEXT,
            ai_gender TEXT,
            interests TEXT
        )
        """
    )

    # Chat sessions
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            my_gender TEXT,
            ai_gender TEXT,
            interests TEXT,
            start_time TEXT,
            end_time TEXT
        )
        """
    )

    # Messages within sessions
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            sender TEXT,          -- "user" or "ai"
            text TEXT,
            timestamp TEXT
        )
        """
    )

    conn.commit()
    conn.close()


def upsert_profile(user_id: int, my_gender: str, ai_gender: str, interests: str):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO profiles (user_id, my_gender, ai_gender, interests)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            my_gender = excluded.my_gender,
            ai_gender = excluded.ai_gender,
            interests = excluded.interests
        """,
        (user_id, my_gender, ai_gender, interests),
    )
    conn.commit()
    conn.close()


def get_profile(user_id: int) -> Optional[Tuple[str, str, str]]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT my_gender, ai_gender, interests FROM profiles WHERE user_id = ?",
        (user_id,),
    )
    row = cur.fetchone()
    conn.close()
    if row:
        return row[0], row[1], row[2]
    return None


def create_session(
    user_id: int, my_gender: str, ai_gender: str, interests: str
) -> int:
    conn = get_connection()
    cur = conn.cursor()
    now = datetime.utcnow().isoformat()
    cur.execute(
        """
        INSERT INTO sessions (user_id, my_gender, ai_gender, interests, start_time)
        VALUES (?, ?, ?, ?, ?)
        """,
        (user_id, my_gender, ai_gender, interests, now),
    )
    session_id = cur.lastrowid
    conn.commit()
    conn.close()
    return session_id


def end_session(session_id: int):
    conn = get_connection()
    cur = conn.cursor()
    now = datetime.utcnow().isoformat()
    cur.execute(
        "UPDATE sessions SET end_time = ? WHERE id = ?",
        (now, session_id),
    )
    conn.commit()
    conn.close()


def log_message(session_id: int, sender: str, text: str):
    conn = get_connection()
    cur = conn.cursor()
    now = datetime.utcnow().isoformat()
    cur.execute(
        """
        INSERT INTO messages (session_id, sender, text, timestamp)
        VALUES (?, ?, ?, ?)
        """,
        (session_id, sender, text, now),
    )
    conn.commit()
    conn.close()


def get_session_messages(session_id: int, limit: int = 20) -> List[Tuple[str, str]]:
    """Return last N (sender, text) pairs for context."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT sender, text
        FROM messages
        WHERE session_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (session_id, limit),
    )
    rows = cur.fetchall()
    conn.close()
    # reverse to chronological
    rows.reverse()
    return rows
