import pytest

import core
import database
from app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    monkeypatch.setattr(core, "EMAILS_ADMIN", {"admin@x.sn"})
    connexion = database.get_connexion()
    for nom, email, role in (("Fatou", "f@x.sn", "agriculteur"), ("Awa", "a@x.sn", "client"),
                             ("Moussa", "m@x.sn", "client")):
        connexion.execute("INSERT INTO utilisateurs (nom, email, mot_de_passe, role) VALUES (?, ?, 'x', ?)",
                          (nom, email, role))
    connexion.execute("""INSERT INTO utilisateurs (nom, email, mot_de_passe, role, email_confirme)
                         VALUES ('Admin', 'admin@x.sn', 'x', 'client', 'admin@x.sn')""")
    connexion.execute("""INSERT INTO recoltes (agriculteur_id, nom, quantite, prix, date_disponibilite, localite)
                         VALUES (1, 'Mil', '100 kg', '500 FCFA / kg', '2026-01-01', 'Thiès')""")
    connexion.execute("""INSERT INTO commandes (recolte_id, client_id, quantite_demandee, statut, montant, commission,
                                                frais_livraison, mode_livraison, date_creation)
                         VALUES (1, 2, '10 kg', 'livree', 5000, 250, 1000, 'livraison', '2026-10-01 10:00:00')""")
    connexion.execute("""INSERT INTO commandes (recolte_id, client_id, quantite_demandee, statut)
                         VALUES (1, 2, '5 kg', 'en_attente')""")
    connexion.commit()
    connexion.close()
    return app.test_client()


def connecter(client, utilisateur_id, role):
    with client.session_transaction() as session:
        session.update(utilisateur_id=utilisateur_id, nom="Test", role=role)


def test_recu_du_client(client):
    connecter(client, 2, "client")
    assert "/commande/1/recu" in client.get("/mes-commandes").get_data(as_text=True)
    page = client.get("/commande/1/recu").get_data(as_text=True)
    assert "REC-000001" in page and "01/10/2026" in page
    assert "Fatou" in page and "Awa" in page and "Mil — 10 kg" in page
    assert "Frais de livraison" in page and "6000 FCFA" in page  # 5000 + 1000 de livraison
    assert "Commission" not in page  # la commission ne regarde pas le client


def test_recu_de_l_agriculteur_avec_commission(client):
    connecter(client, 1, "agriculteur")
    assert "/commande/1/recu" in client.get("/espace-agriculteur/commandes").get_data(as_text=True)
    page = client.get("/commande/1/recu").get_data(as_text=True)
    assert "Commission App Agricole : 250 FCFA" in page and "4750 FCFA" in page


def test_recu_protege(client):
    connecter(client, 3, "client")  # autre client
    assert client.get("/commande/1/recu").status_code == 404
    connecter(client, 2, "client")
    assert client.get("/commande/2/recu").status_code == 404  # pas encore livrée
    connecter(client, 4, "client")  # admin
    assert client.get("/commande/1/recu").status_code == 200
