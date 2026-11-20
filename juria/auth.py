import os
import re
import sqlite3
from typing import Optional

import bcrypt


DB_PATH = os.path.join("data", "juria_app.db")

# Table distincte de la table `users` creee par Chainlit (app.py) dans la
# meme base : les deux schemas sont incompatibles.
USERS_TABLE = "juria_users"

# L'identifiant sert de nom de collection ChromaDB (`store_quizz_<username>`) et
# de dossier d'upload (`data/user_docs/<username>`). ChromaDB n'accepte que
# [a-zA-Z0-9._-] et impose un nom qui finit par une lettre ou un chiffre : on
# autorise lettres, chiffres, `_` et `-` (pas de point, pour exclure `..`),
# 32 caracteres max, sans `_` ni `-` en debut ou fin.
USERNAME_PATTERN = re.compile(r"[a-zA-Z0-9](?:[a-zA-Z0-9_-]{0,30}[a-zA-Z0-9])?")


def valider_username(username: str) -> str:
    """Retourne le username s'il est valide, leve ValueError sinon."""
    if not isinstance(username, str) or not USERNAME_PATTERN.fullmatch(username):
        raise ValueError(
            f"Identifiant invalide : {username!r}. Autorises : lettres sans accent, "
            "chiffres, '_' et '-' (32 caracteres max, ni '_' ni '-' en debut ou fin)."
        )
    return username


def is_dev_mode() -> bool:
    return os.getenv("JURIA_ENV", "dev").lower() == "dev"


def is_petite_config() -> bool:
    """Machine peu puissante : meme en dev, bascule vers l'API Claude (Haiku) plutot
    que Ollama si ANTHROPIC_API_KEY est disponible ; sinon repli sur un modele
    Ollama plus leger que celui par defaut."""
    return os.getenv("JURIA_PETITE_CONFIG", "false").lower() == "true"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def _ensure_users_table():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {USERS_TABLE} (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            display_name TEXT NOT NULL
        )
        """
    )
    # Reprise des comptes crees dans l'ancienne table `users` (schema jurIA),
    # sans la supprimer : elle peut etre celle attendue par Chainlit.
    colonnes = {ligne[1] for ligne in conn.execute("PRAGMA table_info(users)")}
    if {"username", "password_hash", "display_name"} <= colonnes:
        conn.execute(
            f"INSERT OR IGNORE INTO {USERS_TABLE} (username, password_hash, display_name) "
            "SELECT username, password_hash, display_name FROM users"
        )
    conn.commit()
    conn.close()


def get_user_db(username: str) -> Optional[dict]:
    _ensure_users_table()
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        f"SELECT username, password_hash, display_name FROM {USERS_TABLE} WHERE username = ?",
        (username,),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return {"username": row[0], "password_hash": row[1], "display_name": row[2]}


def create_user_db(username: str, password: str, display_name: str):
    valider_username(username)
    _ensure_users_table()
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        f"INSERT INTO {USERS_TABLE} (username, password_hash, display_name) VALUES (?, ?, ?)",
        (username, hash_password(password), display_name),
    )
    conn.commit()
    conn.close()
