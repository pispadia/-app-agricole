import pytest

import database
from app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    connexion = database.get_connexion()
    for nom, email, role in (("Fatou", "f@x.sn", "agriculteur"), ("Awa", "a@x.sn", "client"),
                             ("Moussa", "m@x.sn", "agriculteur")):
        connexion.execute("INSERT INTO utilisateurs (nom, email, mot_de_passe, role) VALUES (?, ?, 'x', ?)",
                          (nom, email, role))
    for agriculteur in (1, 3):
        connexion.execute(
            """INSERT INTO recoltes (agriculteur_id, nom, quantite, prix, date_disponibilite, localite)
               VALUES (?, 'Mil', '100 kg', '500 FCFA / kg', '2026-01-01', 'Thiès')""", (agriculteur,))
    # Commandes d'Awa : livrée et annulée chez Fatou, en attente chez Moussa
    for recolte, statut in ((1, "livree"), (1, "annulee"), (2, "en_attente")):
        connexion.execute("INSERT INTO commandes (recolte_id, client_id, quantite_demandee, statut) VALUES (?, 2, '10 kg', ?)",
                          (recolte, statut))
    connexion.commit()
    connexion.close()
    return app.test_client()


def en_tant_que(client, utilisateur_id, role):
    with client.session_transaction() as session:
        session.update(utilisateur_id=utilisateur_id, nom="Test", role=role)


def notes():
    connexion = database.get_connexion()
    lignes = connexion.execute("SELECT commande_id, note FROM avis_clients ORDER BY commande_id").fetchall()
    connexion.close()
    return [(l["commande_id"], l["note"]) for l in lignes]


def test_noter_un_client_et_voir_sa_fiabilite(client):
    en_tant_que(client, 3, "agriculteur")
    assert "Pas encore noté" in client.get("/espace-agriculteur/commandes").get_data(as_text=True)

    en_tant_que(client, 1, "agriculteur")
    page = client.get("/espace-agriculteur/commandes").get_data(as_text=True)
    assert page.count("Note ce client") == 2 and "1 commande(s) livrée(s)" in page
    client.post("/espace-agriculteur/commandes/1/noter-client", data={"note": "5"})
    client.post("/espace-agriculteur/commandes/2/noter-client", data={"note": "2"})
    client.post("/espace-agriculteur/commandes/2/noter-client", data={"note": "1"})  # une seule note
    assert notes() == [(1, 5), (2, 2)]
    assert "Ta note pour ce client" in client.get("/espace-agriculteur/commandes").get_data(as_text=True)

    # Moussa voit la moyenne avant de confirmer
    en_tant_que(client, 3, "agriculteur")
    assert "3.5 (2 note(s) d" in client.get("/espace-agriculteur/commandes").get_data(as_text=True)
    # Le client voit sa propre note
    en_tant_que(client, 2, "client")
    assert "Ta note de fiabilité" in client.get("/mes-commandes").get_data(as_text=True)


def test_regles_de_notation(client):
    en_tant_que(client, 3, "agriculteur")
    client.post("/espace-agriculteur/commandes/3/noter-client", data={"note": "1"})  # pas terminée
    client.post("/espace-agriculteur/commandes/1/noter-client", data={"note": "1"})  # pas sa commande
    en_tant_que(client, 1, "agriculteur")
    client.post("/espace-agriculteur/commandes/1/noter-client", data={"note": "9"})  # note invalide
    en_tant_que(client, 2, "client")
    assert "/connexion" in client.post("/espace-agriculteur/commandes/1/noter-client", data={"note": "5"}).headers["Location"]
    assert notes() == []
