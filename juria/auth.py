import os
import sqlite3
from typing import Optional

import bcrypt


DB_PATH = os.path.join("data", "juria_app.db")


def is_dev_mode() -> bool:
    return os.getenv("JURIA_ENV", "dev").lower() == "dev"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def _ensure_users_table():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            display_name TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def get_user_db(username: str) -> Optional[dict]:
    _ensure_users_table()
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT username, password_hash, display_name FROM users WHERE username = ?",
        (username,),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return {"username": row[0], "password_hash": row[1], "display_name": row[2]}


def create_user_db(username: str, password: str, display_name: str):
    _ensure_users_table()
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO users (username, password_hash, display_name) VALUES (?, ?, ?)",
        (username, hash_password(password), display_name),
    )
    conn.commit()
    conn.close()
