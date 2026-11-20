"""Tests du script CLI scripts/create_user.py."""

import importlib.util
from pathlib import Path

import pytest

from juria import auth

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "create_user.py"


@pytest.fixture
def create_user():
    """Charge le script comme un module (scripts/ n'est pas un package)."""
    spec = importlib.util.spec_from_file_location("create_user", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _lancer(module, monkeypatch, *args):
    monkeypatch.setattr("sys.argv", ["create_user.py", *args])
    module.main()


def test_cree_l_utilisateur(create_user, db_tmp, monkeypatch, capsys):
    _lancer(create_user, monkeypatch, "--username", "alice", "--password", "pw",
            "--display-name", "Alice D.")

    assert auth.get_user_db("alice")["display_name"] == "Alice D."
    assert "cree avec succes" in capsys.readouterr().out


def test_display_name_par_defaut(create_user, db_tmp, monkeypatch):
    _lancer(create_user, monkeypatch, "--username", "bob", "--password", "pw")

    assert auth.get_user_db("bob")["display_name"] == "bob"


def test_utilisateur_existant(create_user, db_tmp, monkeypatch, capsys):
    auth.create_user_db("alice", "pw", "Alice")

    with pytest.raises(SystemExit) as exc:
        _lancer(create_user, monkeypatch, "--username", "alice", "--password", "autre")

    assert exc.value.code == 1
    assert "existe deja" in capsys.readouterr().out
    assert auth.verify_password("pw", auth.get_user_db("alice")["password_hash"])


def test_username_invalide(create_user, db_tmp, monkeypatch, capsys):
    with pytest.raises(SystemExit) as exc:
        _lancer(create_user, monkeypatch, "--username", "marie@exemple.fr", "--password", "pw")

    assert exc.value.code == 1
    assert "Identifiant invalide" in capsys.readouterr().out
    assert auth.get_user_db("marie@exemple.fr") is None
