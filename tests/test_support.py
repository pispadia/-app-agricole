import pytest

import core
import database
import emails
import push
import routes.support as support
from app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    monkeypatch.setattr(core, "EMAILS_ADMIN", {"admin@x.sn"})
    monkeypatch.setattr(support, "EMAILS_ADMIN", {"admin@x.sn"})
    connexion = database.get_connexion()
    connexion.execute("""INSERT INTO utilisateurs (nom, email, mot_de_passe, role, email_confirme)
                         VALUES ('Admin', 'admin@x.sn', 'x', 'client', 'admin@x.sn')""")
    connexion.execute("INSERT INTO utilisateurs (nom, email, mot_de_passe, role) VALUES ('Fatou', 'f@x.sn', 'x', 'agriculteur')")
    connexion.execute("INSERT INTO utilisateurs (nom, email, mot_de_passe, role) VALUES ('Awa', 'a@x.sn', 'x', 'client')")
    connexion.execute("""INSERT INTO recoltes (agriculteur_id, nom, quantite, prix, date_disponibilite, localite)
                         VALUES (2, 'Mil', '100 kg', '500 FCFA / kg', '2026-01-01', 'Thiès')""")
    connexion.execute("INSERT INTO commandes (recolte_id, client_id, quantite_demandee, statut) VALUES (1, 3, '10 kg', 'confirmee')")
    connexion.commit()
    connexion.close()
    return app.test_client()


@pytest.fixture
def envois(monkeypatch):
    liste = []
    monkeypatch.setattr(support, "envoyer_email", lambda dest, sujet, contenu: liste.append(("email", dest, sujet)))
    monkeypatch.setattr(support.threading, "Thread", lambda target, daemon: type("T", (), {"start": lambda s: target()})())
    monkeypatch.setattr(push, "alerter", lambda *args: liste.append(("push",) + args))
    return liste


def connecter(client, utilisateur_id, role):
    with client.session_transaction() as session:
        session.update(utilisateur_id=utilisateur_id, nom="Test", role=role)


def test_litige_sur_une_commande_puis_reponse(client, envois):
    connecter(client, 3, "client")
    page = client.get("/contact?commande=1").get_data(as_text=True)
    assert 'value="1" selected' in page and "N°1 · Mil" in page
    page = client.post("/contact", data={"categorie": "commande", "commande_id": "1",
                                         "message": "Pas livré depuis une semaine"},
                       follow_redirects=True).get_data(as_text=True)
    assert "demande n°1" in page and "Pas livré depuis une semaine" in page
    assert ("email", "admin@x.sn", "[App Agricole] Nouvelle demande n°1 : Problème sur une commande (non livrée, qualité, quantité...)") in envois

    connecter(client, 1, "client")
    page = client.get("/admin/support").get_data(as_text=True)
    assert "Pas livré depuis une semaine" in page and "vendeur Fatou" in page
    assert "📨 Demandes" in client.get("/admin").get_data(as_text=True)
    client.post("/admin/support/1/repondre", data={"reponse": "Le vendeur livre demain."})
    assert any(e[0] == "email" and e[1] == "a@x.sn" for e in envois)
    assert any(e[0] == "push" and e[1] == 3 for e in envois)

    connecter(client, 3, "client")
    page = client.get("/contact").get_data(as_text=True)
    assert "Le vendeur livre demain." in page and "Traitée" in page


def test_visiteur_sans_compte_et_commande_d_un_autre_ignoree(client, envois):
    client.post("/contact", data={"nom": "Moussa", "email": "m@x.sn", "categorie": "question",
                                  "message": "Livrez-vous à Saint-Louis ?", "commande_id": "1"})
    connexion = database.get_connexion()
    demande = connexion.execute("SELECT * FROM demandes_support").fetchone()
    connexion.close()
    assert demande["nom"] == "Moussa" and demande["utilisateur_id"] is None and demande["commande_id"] is None


def test_demande_incomplete_refusee_et_admin_protege(client, envois):
    client.post("/contact", data={"nom": "X", "email": "pas-un-email", "categorie": "question", "message": "?"})
    client.post("/contact", data={"nom": "X", "email": "x@x.sn", "categorie": "inconnue", "message": "?"})
    connexion = database.get_connexion()
    assert connexion.execute("SELECT COUNT(*) AS n FROM demandes_support").fetchone()["n"] == 0
    connexion.close()
    connecter(client, 3, "client")
    assert client.get("/admin/support").status_code == 302
