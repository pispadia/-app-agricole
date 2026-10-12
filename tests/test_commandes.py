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
                             ("Moussa", "m@x.sn", "agriculteur"), ("Ibou", "i@x.sn", "client")):
        connexion.execute("INSERT INTO utilisateurs (nom, email, mot_de_passe, role) VALUES (?, ?, ?, ?)",
                          (nom, email, "x", role))
    # récolte 1 (Fatou) disponible, récolte 2 (Fatou) épuisée
    for statut in ("disponible", "epuise"):
        connexion.execute(
            """INSERT INTO recoltes (agriculteur_id, nom, quantite, prix, date_disponibilite, localite, statut)
               VALUES (1, 'Mil', '100 kg', '500 FCFA / kg', '2026-11-01', 'Thiès', ?)""", (statut,))
    connexion.commit()
    connexion.close()
    return app.test_client()


def en_tant_que(client, utilisateur_id, role):
    with client.session_transaction() as session:
        session.update(utilisateur_id=utilisateur_id, nom="Test", role=role)


def statut_commande(commande_id=1):
    connexion = database.get_connexion()
    ligne = connexion.execute("SELECT statut FROM commandes WHERE id = ?", (commande_id,)).fetchone()
    connexion.close()
    return ligne["statut"] if ligne else None


def nombre_commandes():
    connexion = database.get_connexion()
    n = connexion.execute("SELECT COUNT(*) AS n FROM commandes").fetchone()["n"]
    connexion.close()
    return n


def commander(client, recolte_id=1, quantite="20 kg"):
    en_tant_que(client, 2, "client")
    return client.post(f"/commander/{recolte_id}", data={"quantite_demandee": quantite}, follow_redirects=True)


def test_cycle_complet_d_une_commande(client):
    page = commander(client).get_data(as_text=True)
    assert "Mes commandes" in page and "En attente" in page

    en_tant_que(client, 1, "agriculteur")
    client.post("/espace-agriculteur/commandes/1/statut", data={"statut": "confirmee"})
    assert statut_commande() == "confirmee"
    client.post("/espace-agriculteur/commandes/1/statut", data={"statut": "livree", "montant": "10000"})
    assert statut_commande() == "livree"

    en_tant_que(client, 2, "client")
    assert "Livrée" in client.get("/mes-commandes").get_data(as_text=True)


def test_transition_interdite(client):
    commander(client)
    en_tant_que(client, 1, "agriculteur")
    client.post("/espace-agriculteur/commandes/1/statut", data={"statut": "livree"})  # sans confirmation
    assert statut_commande() == "en_attente"
    client.post("/espace-agriculteur/commandes/1/statut", data={"statut": "annulee"})
    client.post("/espace-agriculteur/commandes/1/statut", data={"statut": "confirmee"})  # après annulation
    assert statut_commande() == "annulee"


def test_autre_agriculteur_ne_peut_pas_modifier(client):
    commander(client)
    en_tant_que(client, 3, "agriculteur")
    client.post("/espace-agriculteur/commandes/1/statut", data={"statut": "confirmee"})
    assert statut_commande() == "en_attente"


def test_client_annule_seulement_ses_commandes_en_attente(client):
    commander(client)
    en_tant_que(client, 4, "client")  # autre client
    client.post("/mes-commandes/1/annuler")
    assert statut_commande() == "en_attente"
    assert "Mil" not in client.get("/mes-commandes").get_data(as_text=True)

    en_tant_que(client, 2, "client")
    client.post("/mes-commandes/1/annuler")
    assert statut_commande() == "annulee"

    commander(client)
    en_tant_que(client, 1, "agriculteur")
    client.post("/espace-agriculteur/commandes/2/statut", data={"statut": "confirmee"})
    en_tant_que(client, 2, "client")
    client.post("/mes-commandes/2/annuler")
    assert statut_commande(2) == "confirmee"


def test_recolte_epuisee_ne_peut_pas_etre_commandee(client):
    page = commander(client, recolte_id=2).get_data(as_text=True)
    assert "plus disponible" in page
    en_tant_que(client, 2, "client")
    client.post("/panier/ajouter/2", data={"quantite": "5 kg"})
    with client.session_transaction() as session:
        assert session.get("panier", []) == []
    assert nombre_commandes() == 0


def test_panier_ignore_une_recolte_devenue_epuisee(client):
    en_tant_que(client, 2, "client")
    client.post("/panier/ajouter/1", data={"quantite": "5 kg"})
    connexion = database.get_connexion()
    connexion.execute("UPDATE recoltes SET statut = 'epuise' WHERE id = 1")
    connexion.commit()
    connexion.close()
    page = client.post("/panier/valider", follow_redirects=True).get_data(as_text=True)
    assert "Plus disponible" in page
    assert nombre_commandes() == 0


def test_quantite_commandee_validee(client):
    page = commander(client, quantite="beaucoup").get_data(as_text=True)
    assert "nombre positif" in page
    assert nombre_commandes() == 0
