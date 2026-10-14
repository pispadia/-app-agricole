import pytest

import database
import sms
from app import app
from routes import alertes


class ThreadImmediat:
    def __init__(self, target, daemon=None):
        self.target = target

    def start(self):
        self.target()


@pytest.fixture
def envois(monkeypatch):
    liste = []
    monkeypatch.setattr(alertes.threading, "Thread", ThreadImmediat)
    monkeypatch.setattr(alertes, "envoyer_email", lambda dest, sujet, html: liste.append(("email", dest, sujet)))
    monkeypatch.setattr(sms, "alerter", lambda tel, msg: tel and liste.append(("sms", tel, msg)))
    return liste


@pytest.fixture
def client(tmp_path, monkeypatch, envois):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    connexion = database.get_connexion()
    for nom, email, role in (("Fatou", "f@x.sn", "agriculteur"), ("Awa", "a@x.sn", "client"),
                             ("Ibou", "i@x.sn", "client"), ("Moussa", "m@x.sn", "agriculteur")):
        connexion.execute("INSERT INTO utilisateurs (nom, email, mot_de_passe, role) VALUES (?, ?, 'x', ?)",
                          (nom, email, role))
    connexion.commit()
    connexion.close()
    return app.test_client()


def en_tant_que(client, utilisateur_id, role):
    with client.session_transaction() as session:
        session.update(utilisateur_id=utilisateur_id, nom="Test", role=role)


def publier(client, agriculteur_id, nom, localite="Thiès"):
    en_tant_que(client, agriculteur_id, "agriculteur")
    client.post("/espace-agriculteur/nouvelle-recolte", data={
        "nom": nom, "quantite": "100 kg", "prix": "500 FCFA / kg",
        "date_disponibilite": "2026-11-01", "localite": localite})


def test_ajouter_et_retirer_un_favori(client):
    publier(client, 1, "Mil")
    en_tant_que(client, 2, "client")
    page = client.get("/annonce/1").get_data(as_text=True)
    assert "Ajouter aux favoris" in page and "Suivre cet agriculteur" in page

    client.post("/annonce/1/favori")
    assert "Dans mes favoris" in client.get("/annonce/1").get_data(as_text=True)
    page = client.get("/mes-favoris").get_data(as_text=True)
    assert "Annonces gardées (1)" in page and "Mil" in page

    reponse = client.post("/annonce/1/favori", data={"retour": "favoris"})
    assert reponse.headers["Location"].endswith("/mes-favoris")
    assert "Annonces gardées (0)" in client.get("/mes-favoris").get_data(as_text=True)


def test_favoris_reserves_aux_clients(client):
    publier(client, 1, "Mil")
    en_tant_que(client, 4, "agriculteur")
    assert "/connexion" in client.post("/annonce/1/favori").headers["Location"]
    assert "Ajouter aux favoris" not in client.get("/annonce/1").get_data(as_text=True)
    connexion = database.get_connexion()
    assert connexion.execute("SELECT COUNT(*) AS n FROM favoris").fetchone()["n"] == 0
    connexion.close()


def test_annonce_masquee_absente_des_favoris(client):
    publier(client, 1, "Mil")
    en_tant_que(client, 2, "client")
    client.post("/annonce/1/favori")
    connexion = database.get_connexion()
    connexion.execute("UPDATE recoltes SET masquee = 1")
    connexion.commit()
    connexion.close()
    assert "Annonces gardées (0)" in client.get("/mes-favoris").get_data(as_text=True)


def test_suivre_un_agriculteur_previent_de_ses_publications(client, envois):
    en_tant_que(client, 2, "client")
    client.post("/agriculteurs/1/suivre")
    client.post("/agriculteurs/4/suivre", data={"retour": "agriculteur"})
    client.post("/agriculteurs/4/suivre")  # deuxième clic : ne suit plus
    assert "Agriculteurs suivis (1)" in client.get("/mes-favoris").get_data(as_text=True)

    publier(client, 1, "Oignon")
    assert [(e[0], e[1]) for e in envois] == [("email", "a@x.sn")]
    assert envois[0][2] == "Fatou a publié : Oignon à Thiès"

    envois.clear()
    publier(client, 4, "Oignon")
    assert envois == []


def test_alerte_et_suivi_un_seul_message(client, envois):
    en_tant_que(client, 2, "client")
    client.post("/mes-alertes", data={"produit": "mil"})
    client.post("/agriculteurs/1/suivre")
    publier(client, 1, "Mil")
    assert len(envois) == 1 and envois[0][2] == "Nouvelle annonce : Mil à Thiès"


def test_on_ne_suit_que_des_agriculteurs(client):
    en_tant_que(client, 2, "client")
    client.post("/agriculteurs/3/suivre")
    connexion = database.get_connexion()
    assert connexion.execute("SELECT COUNT(*) AS n FROM agriculteurs_suivis").fetchone()["n"] == 0
    connexion.close()


def test_page_agriculteur_bouton_suivre(client):
    en_tant_que(client, 2, "client")
    assert "Suivre : être prévenu" in client.get("/agriculteurs/1/avis").get_data(as_text=True)
    client.post("/agriculteurs/1/suivre", data={"retour": "agriculteur"})
    assert "Tu suis Fatou" in client.get("/agriculteurs/1/avis").get_data(as_text=True)


def test_suppression_de_compte_efface_favoris_et_suivis(client):
    from routes.suppression_compte import effacer_compte
    publier(client, 1, "Mil")
    en_tant_que(client, 2, "client")
    client.post("/annonce/1/favori")
    client.post("/agriculteurs/1/suivre")
    connexion = database.get_connexion()
    effacer_compte(connexion, 2)
    assert connexion.execute("SELECT COUNT(*) AS n FROM favoris").fetchone()["n"] == 0
    assert connexion.execute("SELECT COUNT(*) AS n FROM agriculteurs_suivis").fetchone()["n"] == 0
    connexion.close()
