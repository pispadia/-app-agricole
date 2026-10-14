import pytest

import database
import sms
from app import app
from core import masquer_coordonnees


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    monkeypatch.setattr(sms, "alerter", lambda *args: None)
    connexion = database.get_connexion()
    for nom, email, role in (("Fatou", "f@x.sn", "agriculteur"), ("Awa", "a@x.sn", "client"),
                             ("Ibou", "i@x.sn", "client"), ("Moussa", "m@x.sn", "agriculteur")):
        connexion.execute("INSERT INTO utilisateurs (nom, email, mot_de_passe, role) VALUES (?, ?, ?, ?)",
                          (nom, email, "x", role))
    connexion.execute(
        """INSERT INTO recoltes (agriculteur_id, nom, quantite, prix, date_disponibilite, localite)
           VALUES (1, 'Mil', '100 kg', '500 FCFA / kg', '2026-11-01', 'Thiès')""")
    connexion.execute("INSERT INTO commandes (recolte_id, client_id, quantite_demandee) VALUES (1, 2, '20 kg')")
    connexion.commit()
    connexion.close()
    return app.test_client()


def en_tant_que(client, utilisateur_id, nom, role):
    with client.session_transaction() as session:
        session.update(utilisateur_id=utilisateur_id, nom=nom, role=role)


def messages():
    connexion = database.get_connexion()
    lignes = connexion.execute(
        "SELECT auteur_id, destinataire_id, contenu, lu FROM messages_commande ORDER BY id").fetchall()
    connexion.close()
    return [tuple(ligne) for ligne in lignes]


def test_masquer_coordonnees():
    assert masquer_coordonnees("Appelle au 77 123 45 67") == "Appelle au [numéro masqué]"
    assert masquer_coordonnees("+221771234567 ou 0022177123456") == "[numéro masqué] ou [numéro masqué]"
    assert masquer_coordonnees("écris à awa.diop@gmail.com") == "écris à [e-mail masqué]"
    # Quantités, prix et dates restent lisibles
    assert masquer_coordonnees("20 kg à 25 000 FCFA, le 05/11/2026") == "20 kg à 25 000 FCFA, le 05/11/2026"


def test_conversation_entre_client_et_agriculteur(client):
    en_tant_que(client, 2, "Awa", "client")
    client.post("/commandes/1/messages", data={"contenu": "Vous livrez à Médina ?"})
    en_tant_que(client, 1, "Fatou", "agriculteur")
    assert "1 nouveau" in client.get("/espace-agriculteur/commandes").get_data(as_text=True)
    assert "Nouveaux messages" in client.get("/notifications").get_data(as_text=True)

    page = client.get("/commandes/1/messages").get_data(as_text=True)
    assert "Vous livrez à Médina ?" in page and "Discussion avec Awa" in page
    client.post("/commandes/1/messages", data={"contenu": "Oui, samedi."})
    assert messages() == [(2, 1, "Vous livrez à Médina ?", 1), (1, 2, "Oui, samedi.", 0)]
    assert "1 nouveau" not in client.get("/espace-agriculteur/commandes").get_data(as_text=True)

    en_tant_que(client, 2, "Awa", "client")
    assert "1 nouveau" in client.get("/mes-commandes").get_data(as_text=True)


def test_numeros_masques_dans_les_messages(client):
    en_tant_que(client, 2, "Awa", "client")
    client.post("/commandes/1/messages", data={"contenu": "Appelle-moi au 78 444 55 66 ou a@x.sn"})
    assert messages()[0][2] == "Appelle-moi au [numéro masqué] ou [e-mail masqué]"


def test_message_de_commande_masque(client):
    en_tant_que(client, 2, "Awa", "client")
    client.post("/commander/1", data={"quantite_demandee": "5 kg", "message": "Mon numéro : 771234567"})
    connexion = database.get_connexion()
    message = connexion.execute("SELECT message FROM commandes WHERE id = 2").fetchone()["message"]
    connexion.close()
    assert message == "Mon numéro : [numéro masqué]"


@pytest.mark.parametrize("utilisateur_id, nom, role", [(3, "Ibou", "client"), (4, "Moussa", "agriculteur")])
def test_conversation_privee(client, utilisateur_id, nom, role):
    en_tant_que(client, utilisateur_id, nom, role)
    client.post("/commandes/1/messages", data={"contenu": "Intrus"})
    assert client.get("/commandes/1/messages").status_code == 302
    assert messages() == []


@pytest.mark.parametrize("contenu", ["   ", "x" * 1001])
def test_message_vide_ou_trop_long(client, contenu):
    en_tant_que(client, 2, "Awa", "client")
    client.post("/commandes/1/messages", data={"contenu": contenu})
    assert messages() == []
