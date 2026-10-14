import pytest

import database
import push
import sms
from app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    monkeypatch.setattr(sms, "alerter", lambda *args: None)
    connexion = database.get_connexion()
    connexion.execute("INSERT INTO utilisateurs (nom, email, mot_de_passe, role) VALUES ('Fatou', 'f@x.sn', 'x', 'agriculteur')")
    connexion.execute("INSERT INTO utilisateurs (nom, email, mot_de_passe, role) VALUES ('Awa', 'a@x.sn', 'x', 'client')")
    connexion.execute("INSERT INTO utilisateurs (nom, email, mot_de_passe, role) VALUES ('Moussa', 'm@x.sn', 'x', 'client')")
    connexion.execute("""INSERT INTO recoltes (agriculteur_id, nom, quantite, prix, date_disponibilite, localite)
                         VALUES (1, 'Mil', '1 tonne', '500 FCFA / kg', '2026-01-01', 'Thiès')""")
    connexion.commit()
    connexion.close()
    return app.test_client()


@pytest.fixture
def alertes(monkeypatch):
    liste = []
    monkeypatch.setattr(push, "alerter", lambda uid, tel, message, url="/": liste.append((uid, message)))
    return liste


def connecter(client, utilisateur_id, role):
    with client.session_transaction() as session:
        session.update(utilisateur_id=utilisateur_id, nom="Test", role=role)


def commande():
    connexion = database.get_connexion()
    ligne = connexion.execute("SELECT * FROM commandes WHERE id = 1").fetchone()
    connexion.close()
    return ligne


def offre(client, action, prix=""):
    return client.post("/commandes/1/offre", data={"action": action, "prix": prix}, follow_redirects=True).get_data(as_text=True)


def test_offre_contre_offre_puis_accord(client, alertes):
    connecter(client, 2, "client")
    client.post("/commander/1", data={"quantite_demandee": "500 kg", "mode_livraison": "retrait",
                                      "prix_propose": "400 FCFA / kg"})
    assert commande()["negociation"] == "proposee" and commande()["prix_propose"] == "400 FCFA / kg"
    assert "Prix proposé : 400 FCFA / kg" in alertes[-1][1]

    connecter(client, 1, "agriculteur")
    page = client.get("/espace-agriculteur/commandes").get_data(as_text=True)
    assert "Le client propose : 400 FCFA / kg" in page and "Faire une contre-offre" in page
    # Impossible de confirmer tant que l'offre attend une réponse
    page = client.post("/espace-agriculteur/commandes/1/statut", data={"statut": "confirmee"},
                       follow_redirects=True).get_data(as_text=True)
    assert "abord à l" in page and commande()["statut"] == "en_attente"
    offre(client, "contre_offre", "450 FCFA / kg")
    assert commande()["negociation"] == "contre_offre" and alertes[-1][0] == 2

    connecter(client, 2, "client")
    page = client.get("/mes-commandes").get_data(as_text=True)
    assert "agriculteur : 450 FCFA / kg" in page
    offre(client, "accepter")
    assert commande()["negociation"] == "acceptee" and commande()["prix_propose"] == "450 FCFA / kg"
    assert "Prix convenu : 450 FCFA / kg" in client.get("/mes-commandes").get_data(as_text=True)

    connecter(client, 1, "agriculteur")
    client.post("/espace-agriculteur/commandes/1/statut", data={"statut": "confirmee"})
    assert commande()["statut"] == "confirmee"


def test_agriculteur_accepte_directement_et_droits(client, alertes):
    connecter(client, 2, "client")
    client.post("/commander/1", data={"quantite_demandee": "500 kg", "mode_livraison": "retrait",
                                      "prix_propose": "420 FCFA / kg"})
    connecter(client, 3, "client")  # autre client
    assert client.post("/commandes/1/offre", data={"action": "accepter"}).status_code == 404
    connecter(client, 2, "client")
    assert "attend plus de réponse" in offre(client, "accepter")  # c'est à l'agriculteur de répondre
    connecter(client, 1, "agriculteur")
    offre(client, "accepter")
    assert commande()["negociation"] == "acceptee" and commande()["prix_propose"] == "420 FCFA / kg"


def test_prix_invalide_refuse(client, alertes):
    connecter(client, 2, "client")
    page = client.post("/commander/1", data={"quantite_demandee": "500 kg", "mode_livraison": "retrait",
                                             "prix_propose": "pas cher"}, follow_redirects=True).get_data(as_text=True)
    assert "Le prix doit être un montant positif" in page and commande() is None
