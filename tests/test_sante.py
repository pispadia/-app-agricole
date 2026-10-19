import pytest

import database
from app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    return app.test_client()


def test_sante_repond_ok_sans_connexion(client):
    reponse = client.get("/sante")
    assert reponse.status_code == 200
    assert reponse.data == b"ok"
    assert reponse.headers["Cache-Control"] == "no-store"


def test_sante_accepte_head(client):
    assert client.head("/sante").status_code == 200
