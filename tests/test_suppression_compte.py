import pytest
from werkzeug.security import generate_password_hash

import database
from app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    connexion = database.get_connexion()
    mdp = generate_password_hash("motdepasse")
    connexion.execute("""INSERT INTO utilisateurs (nom, email, mot_de_passe, role, telephone)
                         VALUES ('Fatou', 'f@x.sn', ?, 'agriculteur', '771234567')""", (mdp,))
    connexion.execute("INSERT INTO utilisateurs (nom, email, mot_de_passe, role) VALUES ('Awa', 'a@x.sn', ?, 'client')", (mdp,))
    connexion.execute("""INSERT INTO recoltes (agriculteur_id, nom, quantite, prix, date_disponibilite, localite)
                         VALUES (1, 'Mil', '100 kg', '500 FCFA / kg', '2026-01-01', 'Thiès')""")
    connexion.execute("""INSERT INTO commandes (recolte_id, client_id, quantite_demandee, statut, montant, commission,
                                                commission_payee, adresse_livraison)
                         VALUES (1, 2, '10 kg', 'livree', 5000, 250, 1, 'Rue 10, Dakar')""")
    connexion.commit()
    connexion.close()
    return app.test_client()


def connecter(client, utilisateur_id, role):
    with client.session_transaction() as session:
        session.update(utilisateur_id=utilisateur_id, nom="Test", role=role)


def ligne(requete, *params):
    connexion = database.get_connexion()
    resultat = connexion.execute(requete, params).fetchone()
    connexion.close()
    return resultat


def test_suppression_efface_les_donnees_et_garde_les_commandes(client):
    connecter(client, 2, "client")
    assert "/mon-profil/supprimer" in client.get("/mon-profil").get_data(as_text=True)
    page = client.post("/mon-profil/supprimer", data={"confirmation": "supprimer", "mot_de_passe": "motdepasse"},
                       follow_redirects=True).get_data(as_text=True)
    assert "Ton compte a été supprimé" in page
    utilisateur = ligne("SELECT * FROM utilisateurs WHERE id = 2")
    assert utilisateur["nom"] == "Compte supprimé" and "a@x.sn" not in utilisateur["email"]
    assert utilisateur["telephone"] is None and utilisateur["suspendu"] == 1
    commande = ligne("SELECT * FROM commandes WHERE id = 1")
    assert commande["montant"] == 5000 and commande["adresse_livraison"] is None
    # Plus possible de se connecter avec l'ancienne adresse
    page = client.post("/connexion", data={"email": "a@x.sn", "mot_de_passe": "motdepasse"},
                       follow_redirects=True).get_data(as_text=True)
    assert "Bonjour" not in page


def test_annonces_retirees_quand_l_agriculteur_part(client):
    connecter(client, 1, "agriculteur")
    client.post("/mon-profil/supprimer", data={"confirmation": "SUPPRIMER", "mot_de_passe": "motdepasse"})
    assert ligne("SELECT masquee FROM recoltes WHERE id = 1")["masquee"] == 1
    assert "Mil" not in client.get("/catalogue").get_data(as_text=True)


def test_confirmation_et_mot_de_passe_obligatoires(client):
    connecter(client, 2, "client")
    client.post("/mon-profil/supprimer", data={"confirmation": "oui", "mot_de_passe": "motdepasse"})
    client.post("/mon-profil/supprimer", data={"confirmation": "SUPPRIMER", "mot_de_passe": "faux"})
    assert ligne("SELECT nom FROM utilisateurs WHERE id = 2")["nom"] == "Awa"


def test_refusee_si_commande_en_cours_ou_commission_due(client):
    connexion = database.get_connexion()
    connexion.execute("""INSERT INTO commandes (recolte_id, client_id, quantite_demandee, statut)
                         VALUES (1, 2, '5 kg', 'en_attente')""")
    connexion.execute("UPDATE commandes SET commission_payee = 0 WHERE id = 1")
    connexion.commit()
    connexion.close()
    connecter(client, 1, "agriculteur")
    page = client.get("/mon-profil/supprimer").get_data(as_text=True)
    assert "1 commande(s) en cours" in page and "Commission due à la plateforme : 250 FCFA" in page
    client.post("/mon-profil/supprimer", data={"confirmation": "SUPPRIMER", "mot_de_passe": "motdepasse"})
    assert ligne("SELECT nom FROM utilisateurs WHERE id = 1")["nom"] == "Fatou"
