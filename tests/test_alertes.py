import pytest

import database
import sms
from app import app
from routes import alertes


class ThreadImmediat:
    """Exécute l'envoi tout de suite, pour pouvoir vérifier les messages dans le test."""
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
    for nom, email, role, tel in (("Fatou", "f@x.sn", "agriculteur", None), ("Awa", "a@x.sn", "client", "77 000 00 00"),
                                  ("Ibou", "i@x.sn", "client", None)):
        connexion.execute("INSERT INTO utilisateurs (nom, email, mot_de_passe, role, telephone) VALUES (?, ?, 'x', ?, ?)",
                          (nom, email, role, tel))
    connexion.commit()
    connexion.close()
    return app.test_client()


def en_tant_que(client, utilisateur_id, role):
    with client.session_transaction() as session:
        session.update(utilisateur_id=utilisateur_id, nom="Test", role=role)


def publier(client, nom, localite):
    en_tant_que(client, 1, "agriculteur")
    client.post("/espace-agriculteur/nouvelle-recolte", data={
        "nom": nom, "quantite": "100 kg", "prix": "500 FCFA / kg",
        "date_disponibilite": "2026-11-01", "localite": localite})


def test_alerte_declenchee_par_une_publication(client, envois):
    en_tant_que(client, 2, "client")
    client.post("/mes-alertes", data={"produit": "Mil", "localite": "thies"})
    en_tant_que(client, 3, "client")
    client.post("/mes-alertes", data={"produit": "oignons"})  # partout

    publier(client, "Mil souna", "Thiès")
    assert [(e[0], e[1]) for e in envois] == [("email", "a@x.sn"), ("sms", "77 000 00 00")]
    assert "Mil souna à Thiès" in envois[0][2] and "/annonce/1" in envois[1][2]

    envois.clear()
    publier(client, "Mil", "Kaolack")      # pas la bonne localité
    publier(client, "Arachide", "Thiès")   # pas le bon produit
    assert envois == []
    publier(client, "Oignon violet", "Potou")
    assert [(e[0], e[1]) for e in envois] == [("email", "i@x.sn")]


def test_un_seul_message_par_client(client, envois):
    en_tant_que(client, 3, "client")
    client.post("/mes-alertes", data={"produit": "mil"})
    client.post("/mes-alertes", data={"produit": "mil", "localite": "Thiès"})
    publier(client, "Mil", "Thiès")
    assert len(envois) == 1


def test_gerer_ses_alertes(client):
    en_tant_que(client, 2, "client")
    client.post("/mes-alertes", data={"produit": "  "})
    for i in range(alertes.MAX_ALERTES + 1):
        client.post("/mes-alertes", data={"produit": f"mil {i}"})
    page = client.get("/mes-alertes").get_data(as_text=True)
    assert f"({alertes.MAX_ALERTES}/{alertes.MAX_ALERTES})" in page

    en_tant_que(client, 3, "client")
    client.post("/mes-alertes/1/supprimer")  # alerte d'un autre client
    en_tant_que(client, 2, "client")
    assert f"({alertes.MAX_ALERTES}/" in client.get("/mes-alertes").get_data(as_text=True)
    client.post("/mes-alertes/1/supprimer")
    assert f"({alertes.MAX_ALERTES - 1}/" in client.get("/mes-alertes").get_data(as_text=True)


def test_reserve_aux_clients(client):
    en_tant_que(client, 1, "agriculteur")
    assert client.get("/mes-alertes").status_code == 302
