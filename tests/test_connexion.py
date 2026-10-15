import pytest

import database
from app import app
from routes import comptes

LIEU = {"pays": "SN", "region": "Dakar", "departement": "Dakar", "commune": "Yoff"}  # adresse demandée à l'inscription


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    client = app.test_client()
    client.post("/inscription", data={**LIEU, 
        "nom": "Awa", "email": "awa@exemple.sn", "mot_de_passe": "bon-mot-de-passe", "role": "client",
    })
    return client


def se_connecter(client, mot_de_passe, email="awa@exemple.sn"):
    return client.post("/connexion", data={"email": email, "mot_de_passe": mot_de_passe},
                       follow_redirects=True).get_data(as_text=True)


def test_bon_mot_de_passe_connecte(client):
    se_connecter(client, "bon-mot-de-passe")
    with client.session_transaction() as session:
        assert session.get("role") == "client"


def test_blocage_apres_trop_d_echecs(client):
    for _ in range(comptes.MAX_ECHECS):
        assert "incorrect" in se_connecter(client, "faux")
    # Même le bon mot de passe est refusé pendant le blocage
    page = se_connecter(client, "bon-mot-de-passe")
    assert "Trop de tentatives" in page
    with client.session_transaction() as session:
        assert "utilisateur_id" not in session
    # Le blocage ne dépend pas des majuscules de l'email
    assert "Trop de tentatives" in se_connecter(client, "faux", email="AWA@exemple.sn")


def test_blocage_expire(client, monkeypatch):
    for _ in range(comptes.MAX_ECHECS):
        se_connecter(client, "faux")
    maintenant = comptes.time.time()
    monkeypatch.setattr(comptes.time, "time", lambda: maintenant + comptes.DUREE_BLOCAGE + 1)
    se_connecter(client, "bon-mot-de-passe")
    with client.session_transaction() as session:
        assert session.get("role") == "client"


def test_succes_remet_le_compteur_a_zero(client):
    for _ in range(comptes.MAX_ECHECS - 1):
        se_connecter(client, "faux")
    se_connecter(client, "bon-mot-de-passe")
    client.get("/deconnexion")
    for _ in range(comptes.MAX_ECHECS - 1):
        se_connecter(client, "faux")
    se_connecter(client, "bon-mot-de-passe")
    with client.session_transaction() as session:
        assert session.get("role") == "client"
