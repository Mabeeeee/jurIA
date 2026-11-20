"""Tests du point d'entree Chainlit (app.py).

app.py execute du code des l'import (creation de data/juria_app.db, choix du
mode d'authentification selon JURIA_ENV). On l'importe donc depuis un dossier
temporaire, avec la variable d'environnement voulue, a chaque test.
"""

import importlib.util
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import chainlit as cl
import pytest

from juria import auth

APP = Path(__file__).resolve().parent.parent / "app.py"


@pytest.fixture
def charger_app(tmp_path, monkeypatch, db_tmp):
    """Fabrique : charger_app(env="dev") importe app.py depuis tmp_path."""
    monkeypatch.chdir(tmp_path)

    def _charger(env="dev"):
        monkeypatch.setenv("JURIA_ENV", env)
        spec = importlib.util.spec_from_file_location("app_sous_test", APP)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    return _charger


class FauxSession(dict):
    def set(self, cle, valeur):
        self[cle] = valeur


@pytest.fixture
def session(monkeypatch):
    return FauxSession()


def _brancher(app, monkeypatch, session):
    """Remplace cl dans app par une version ou user_session est un simple dict."""
    monkeypatch.setattr(app, "cl", SimpleNamespace(
        user_session=session, Message=lambda content: SimpleNamespace(content=content),
        User=cl.User,
    ))


# ---------------------------------------------------------------------------
# Base SQLite
# ---------------------------------------------------------------------------

def _colonnes(chemin, table):
    conn = sqlite3.connect(chemin)
    noms = [ligne[1] for ligne in conn.execute(f"PRAGMA table_info({table})")]
    conn.close()
    return noms


class TestInitDb:

    def test_tables_chainlit_creees(self, charger_app, tmp_path):
        charger_app()

        conn = sqlite3.connect(tmp_path / "data" / "juria_app.db")
        tables = {t for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
        assert {"users", "threads", "steps", "elements", "feedbacks"} <= tables

    def test_idempotent(self, charger_app):
        app = charger_app()
        app._init_db()  # deuxieme appel : aucune erreur

    def test_migration_d_un_ancien_schema(self, charger_app, tmp_path):
        (tmp_path / "data").mkdir()
        chemin = tmp_path / "data" / "juria_app.db"
        conn = sqlite3.connect(chemin)
        conn.execute('CREATE TABLE steps ("id" TEXT PRIMARY KEY)')
        conn.execute('CREATE TABLE elements ("id" TEXT PRIMARY KEY)')
        conn.close()

        charger_app()

        assert {"tags", "language"} <= set(_colonnes(chemin, "steps"))
        assert "props" in _colonnes(chemin, "elements")


# ---------------------------------------------------------------------------
# Authentification
# ---------------------------------------------------------------------------

class TestAuthentification:

    async def test_mode_dev_connexion_automatique(self, charger_app):
        app = charger_app("dev")

        user = await app.dev_auth_callback({})

        assert user.identifier == "dev"
        assert not hasattr(app, "auth_callback")

    @pytest.fixture
    def app_prod(self, charger_app, monkeypatch):
        """app.py en mode prod, avec une 'base' d'utilisateurs en memoire."""
        app = charger_app("prod")
        utilisateurs = {"alice": {"username": "alice", "display_name": "Alice D.",
                                  "password_hash": auth.hash_password("s3cret")}}
        monkeypatch.setattr(app, "get_user_db", utilisateurs.get)
        return app

    async def test_mode_prod_mot_de_passe(self, app_prod):
        user = await app_prod.auth_callback("alice", "s3cret")

        assert user.identifier == "alice"
        assert user.metadata == {"role": "user", "display_name": "Alice D."}
        assert not hasattr(app_prod, "dev_auth_callback")

    @pytest.mark.parametrize("username, password", [("alice", "faux"), ("inconnu", "s3cret")])
    async def test_mode_prod_refus(self, app_prod, username, password):
        assert await app_prod.auth_callback(username, password) is None

    async def test_creer_un_compte_apres_le_premier_lancement(self, charger_app, tmp_path):
        # Regression : app.py (Chainlit) et auth.py creaient tous deux une table
        # `users` dans la meme base ; create_user_db echouait apres le 1er lancement.
        app = charger_app("prod")  # _init_db() cree la table users de Chainlit

        auth.create_user_db("alice", "s3cret", "Alice")

        assert await app.auth_callback("alice", "s3cret") is not None
        # La table de Chainlit garde son schema
        assert "identifier" in _colonnes(tmp_path / "data" / "juria_app.db", "users")


# ---------------------------------------------------------------------------
# Handlers de conversation
# ---------------------------------------------------------------------------

async def test_starters(charger_app):
    app = charger_app()

    starters = await app.set_starters()

    assert [s.label for s in starters] == [
        "Responsabilite contractuelle", "Dol et erreur", "Prescription penale",
    ]


async def test_nouvelle_conversation_historique_vide(charger_app, monkeypatch, session):
    app = charger_app()
    _brancher(app, monkeypatch, session)

    await app.start()

    assert session["history"] == []


async def test_reprise_reconstruit_l_historique(charger_app, monkeypatch, session):
    app = charger_app()
    _brancher(app, monkeypatch, session)
    thread = {"steps": [
        {"type": "user_message", "output": "Qu'est-ce que le dol ?"},
        {"type": "tool", "output": "resultat de recherche"},      # ignore
        {"type": "assistant_message", "output": "Le dol est..."},
        {"type": "assistant_message", "output": ""},              # vide : ignore
    ]}

    await app.on_chat_resume(thread)

    assert session["history"] == [
        {"role": "user", "content": "Qu'est-ce que le dol ?"},
        {"role": "assistant", "content": "Le dol est..."},
    ]


async def test_message_ajoute_question_et_reponse_a_l_historique(
        charger_app, monkeypatch, session):
    app = charger_app()
    _brancher(app, monkeypatch, session)
    session["history"] = [{"role": "user", "content": "avant"}]
    vu_par_le_llm = []

    async def faux_stream(history, msg):
        vu_par_le_llm.extend(history)
        return "Reponse"

    monkeypatch.setattr(app, "stream_response", faux_stream)

    await app.main(SimpleNamespace(content="Ma question"))

    assert vu_par_le_llm[-1] == {"role": "user", "content": "Ma question"}
    assert session["history"][-1] == {"role": "assistant", "content": "Reponse"}
    assert len(session["history"]) == 3
