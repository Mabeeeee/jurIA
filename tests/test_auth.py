"""Tests de l'authentification et des modes d'execution (juria/auth.py)."""

import sqlite3

import pytest

from juria import auth


# ---------------------------------------------------------------------------
# Variables d'environnement
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("valeur, attendu", [
    (None, True),        # non definie -> dev par defaut
    ("dev", True),
    ("DEV", True),
    ("prod", False),
    ("production", False),
])
def test_is_dev_mode(monkeypatch, valeur, attendu):
    if valeur is None:
        monkeypatch.delenv("JURIA_ENV", raising=False)
    else:
        monkeypatch.setenv("JURIA_ENV", valeur)

    assert auth.is_dev_mode() is attendu


@pytest.mark.parametrize("valeur, attendu", [
    (None, False),
    ("true", True),
    ("True", True),
    ("false", False),
    ("1", False),        # seule la chaine "true" active la petite config
])
def test_is_petite_config(monkeypatch, valeur, attendu):
    if valeur is None:
        monkeypatch.delenv("JURIA_PETITE_CONFIG", raising=False)
    else:
        monkeypatch.setenv("JURIA_PETITE_CONFIG", valeur)

    assert auth.is_petite_config() is attendu


# ---------------------------------------------------------------------------
# Mots de passe
# ---------------------------------------------------------------------------

class TestMotsDePasse:

    def test_hash_bcrypt_et_verification(self):
        h = auth.hash_password("s3cret")

        assert h.startswith("$2")  # prefixe bcrypt
        assert "s3cret" not in h
        assert auth.verify_password("s3cret", h)

    def test_mauvais_mot_de_passe_refuse(self):
        assert not auth.verify_password("autre", auth.hash_password("s3cret"))

    def test_sel_aleatoire(self):
        assert auth.hash_password("x") != auth.hash_password("x")

    def test_caracteres_accentues(self):
        assert auth.verify_password("été€", auth.hash_password("été€"))


# ---------------------------------------------------------------------------
# Utilisateurs en base (SQLite temporaire, fixture db_tmp)
# ---------------------------------------------------------------------------

class TestUtilisateurs:

    def test_utilisateur_inconnu(self, db_tmp):
        assert auth.get_user_db("personne") is None

    def test_creer_puis_lire(self, db_tmp):
        auth.create_user_db("alice", "s3cret", "Alice D.")

        user = auth.get_user_db("alice")

        assert user["username"] == "alice"
        assert user["display_name"] == "Alice D."
        assert auth.verify_password("s3cret", user["password_hash"])

    def test_mot_de_passe_jamais_stocke_en_clair(self, db_tmp):
        auth.create_user_db("alice", "s3cret", "Alice")

        conn = sqlite3.connect(db_tmp)
        (stocke,) = conn.execute("SELECT password_hash FROM juria_users").fetchone()
        conn.close()

        assert stocke != "s3cret"

    def test_doublon_refuse(self, db_tmp):
        auth.create_user_db("alice", "a", "Alice")

        with pytest.raises(sqlite3.IntegrityError):
            auth.create_user_db("alice", "b", "Alice bis")

    @pytest.mark.parametrize("username", [
        "alice", "dev", "a", "marie_dupont", "jean-pierre2", "A1", "x" * 32,
    ])
    def test_username_valide(self, username):
        assert auth.valider_username(username) == username

    @pytest.mark.parametrize("username", [
        "", "marie@exemple.fr", "jean pierre", "élodie", "a.b", "..", "../x",
        "-alice", "alice-", "_alice", "alice_", "x" * 33,
    ])
    def test_username_invalide(self, username):
        with pytest.raises(ValueError, match="Identifiant invalide"):
            auth.valider_username(username)

    def test_creation_refusee_si_username_invalide(self, db_tmp):
        with pytest.raises(ValueError):
            auth.create_user_db("marie@exemple.fr", "pw", "Marie")

        assert auth.get_user_db("marie@exemple.fr") is None

    def test_reprise_des_comptes_de_l_ancienne_table_users(self, db_tmp, tmp_path):
        (tmp_path / "data").mkdir()
        conn = sqlite3.connect(db_tmp)
        conn.execute("CREATE TABLE users (username TEXT PRIMARY KEY, "
                     "password_hash TEXT NOT NULL, display_name TEXT NOT NULL)")
        conn.execute("INSERT INTO users VALUES (?, ?, ?)",
                     ("alice", auth.hash_password("s3cret"), "Alice"))
        conn.commit()
        conn.close()

        user = auth.get_user_db("alice")

        assert auth.verify_password("s3cret", user["password_hash"])
        conn = sqlite3.connect(db_tmp)
        assert conn.execute("SELECT count(*) FROM users").fetchone() == (1,)  # pas supprimee
        conn.close()

    def test_table_users_de_chainlit_ignoree(self, db_tmp, tmp_path):
        (tmp_path / "data").mkdir()
        conn = sqlite3.connect(db_tmp)
        conn.execute('CREATE TABLE users ("id" TEXT PRIMARY KEY, "identifier" TEXT UNIQUE)')
        conn.execute("INSERT INTO users VALUES ('1', 'dev')")
        conn.commit()
        conn.close()

        assert auth.get_user_db("dev") is None
        auth.create_user_db("alice", "pw", "Alice")
        assert auth.get_user_db("alice")["display_name"] == "Alice"

    def test_cree_le_dossier_et_la_table(self, db_tmp, tmp_path):
        auth._ensure_users_table()
        auth._ensure_users_table()  # idempotent

        assert (tmp_path / "data" / "juria_app.db").exists()
