import pytest

import database
from app import app
from langues import WOLOF


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    return app.test_client()


def test_francais_par_defaut(client):
    page = client.get("/").get_data(as_text=True)
    assert "Bienvenue sur l" in page and "🌍 Wolof" in page


def test_passer_en_wolof_et_revenir(client):
    page = client.get("/langue/wo", headers={"Referer": "http://localhost/connexion"}, follow_redirects=True)
    texte = page.get_data(as_text=True)
    assert page.request.path == "/connexion"  # retour sur la page d'origine
    assert "Baatu jàll" in texte and "🌍 Français" in texte
    assert "Dalal ak jàmm" in client.get("/").get_data(as_text=True)
    client.get("/langue/fr")
    assert "Bienvenue sur l" in client.get("/").get_data(as_text=True)


def test_langue_inconnue_ignoree(client):
    client.get("/langue/xx")
    assert "Bienvenue sur l" in client.get("/").get_data(as_text=True)


def test_espace_agriculteur_en_wolof_et_langue_gardee_apres_deconnexion(client):
    connexion = database.get_connexion()
    connexion.execute("INSERT INTO utilisateurs (nom, email, mot_de_passe, role) VALUES ('Fatou', 'f@x.sn', 'x', 'agriculteur')")
    connexion.commit()
    connexion.close()
    client.get("/langue/wo")
    with client.session_transaction() as session:
        session.update(utilisateur_id=1, nom="Fatou", role="agriculteur")
    page = client.get("/espace-agriculteur").get_data(as_text=True)
    assert "Bérëbu beykat bi" in page and "Siiwaloo benn ngóob ba leegi." in page
    client.get("/deconnexion")
    assert "Dalal ak jàmm" in client.get("/").get_data(as_text=True)


def test_traductions_non_vides():
    assert all(texte.strip() for texte in WOLOF.values())
