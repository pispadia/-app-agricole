import pytest

import database
from app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    monkeypatch.setenv("EMAIL_CONTACT", "contact@app.sn")
    return app.test_client()


def test_pages_legales(client):
    conditions = client.get("/conditions").get_data(as_text=True)
    assert "Conditions générales d'utilisation" in conditions and "5.0 %" in conditions
    assert "contact@app.sn" in conditions
    confidentialite = client.get("/confidentialite").get_data(as_text=True)
    assert "2008-12" in confidentialite and "contact@app.sn" in confidentialite


def test_liens_dans_le_pied_de_page_et_a_l_inscription(client):
    accueil = client.get("/").get_data(as_text=True)
    assert 'href="/conditions"' in accueil and 'href="/confidentialite"' in accueil
    inscription = client.get("/inscription").get_data(as_text=True)
    assert 'name="conditions" required' in inscription
