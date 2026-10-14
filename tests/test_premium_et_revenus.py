from datetime import date, timedelta

import pytest

import core
import database
from app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    monkeypatch.setattr(core, "EMAILS_ADMIN", {"admin@x.sn"})
    connexion = database.get_connexion()
    for nom, email, role in (("Fatou", "f@x.sn", "agriculteur"), ("Awa", "a@x.sn", "client"),
                             ("Admin", "admin@x.sn", "client"), ("Moussa", "m@x.sn", "agriculteur")):
        connexion.execute("INSERT INTO utilisateurs (nom, email, mot_de_passe, role) VALUES (?, ?, ?, ?)",
                          (nom, email, "x", role))
    connexion.execute("UPDATE utilisateurs SET email_confirme = email WHERE email = 'admin@x.sn'")
    for agriculteur_id, nom in ((1, "Mil"), (4, "Arachide")):
        connexion.execute(
            """INSERT INTO recoltes (agriculteur_id, nom, quantite, prix, date_disponibilite, localite)
               VALUES (?, ?, '100 kg', '500 FCFA / kg', '2026-11-01', 'Thiès')""", (agriculteur_id, nom))
    connexion.commit()
    connexion.close()
    return app.test_client()


def en_tant_que(client, utilisateur_id, role):
    with client.session_transaction() as session:
        session.update(utilisateur_id=utilisateur_id, nom="Test", role=role)


def requete(sql, parametres=()):
    connexion = database.get_connexion()
    ligne = connexion.execute(sql, parametres).fetchone()
    connexion.close()
    return ligne


def rendre_premium(utilisateur_id, jours=10):
    connexion = database.get_connexion()
    connexion.execute("UPDATE utilisateurs SET premium_jusqu_au = ? WHERE id = ?",
                      ((date.today() + timedelta(days=jours)).isoformat(), utilisateur_id))
    connexion.commit()
    connexion.close()


def livrer_une_commande(client, montant="20 000"):
    en_tant_que(client, 2, "client")
    client.post("/commander/1", data={"quantite_demandee": "20 kg"})
    en_tant_que(client, 1, "agriculteur")
    client.post("/espace-agriculteur/commandes/1/statut", data={"statut": "confirmee"})
    return client.post("/espace-agriculteur/commandes/1/statut",
                       data={"statut": "livree", "montant": montant}, follow_redirects=True)


# --- Commission sur les ventes

def test_commission_calculee_a_la_livraison(client):
    page = livrer_une_commande(client).get_data(as_text=True)
    commande = requete("SELECT * FROM commandes WHERE id = 1")
    assert commande["statut"] == "livree"
    assert commande["montant"] == 20000
    assert commande["commission"] == round(20000 * core.TAUX_COMMISSION)
    assert "Commission à régler" in page


def test_livraison_sans_montant_refusee(client):
    livrer_une_commande(client, montant="")
    assert requete("SELECT statut FROM commandes WHERE id = 1")["statut"] == "confirmee"


def test_admin_suit_et_encaisse_les_commissions(client):
    livrer_une_commande(client)
    en_tant_que(client, 3, "client")
    page = client.get("/admin").get_data(as_text=True)
    assert "Fatou" in page and "à encaisser : <strong>1000 FCFA" in page
    client.post("/admin/commissions/1/reglee")
    assert requete("SELECT commission_payee FROM commandes WHERE id = 1")["commission_payee"] == 1
    assert "Commissions encaissées : <strong>1000 FCFA" in client.get("/admin").get_data(as_text=True)


def test_admin_reserve_aux_administrateurs(client):
    livrer_une_commande(client)
    en_tant_que(client, 2, "client")
    assert client.get("/admin").status_code == 302
    client.post("/admin/commissions/1/reglee")
    assert requete("SELECT commission_payee FROM commandes WHERE id = 1")["commission_payee"] == 0


# --- Abonnement Premium

def test_paiement_premium_valide_par_admin(client):
    en_tant_que(client, 1, "agriculteur")
    client.post("/premium", data={"reference": "WAVE-123"})
    assert requete("SELECT statut FROM paiements_premium WHERE id = 1")["statut"] == "en_attente"
    assert core.date_fin_premium(requete("SELECT * FROM utilisateurs WHERE id = 1")) is None

    en_tant_que(client, 3, "client")
    assert "WAVE-123" in client.get("/admin").get_data(as_text=True)
    client.post("/admin/paiements/1/valider")
    fin = requete("SELECT premium_jusqu_au FROM utilisateurs WHERE id = 1")["premium_jusqu_au"]
    assert fin == (date.today() + timedelta(days=core.DUREE_PREMIUM_JOURS)).isoformat()
    # Un paiement déjà traité ne peut pas être validé une seconde fois
    client.post("/admin/paiements/1/valider")
    assert requete("SELECT premium_jusqu_au FROM utilisateurs WHERE id = 1")["premium_jusqu_au"] == fin


def test_renouvellement_prolonge_l_abonnement(client):
    rendre_premium(1, jours=10)
    en_tant_que(client, 1, "agriculteur")
    client.post("/premium", data={"reference": "WAVE-456"})
    en_tant_que(client, 3, "client")
    client.post("/admin/paiements/1/valider")
    attendu = (date.today() + timedelta(days=10 + core.DUREE_PREMIUM_JOURS)).isoformat()
    assert requete("SELECT premium_jusqu_au FROM utilisateurs WHERE id = 1")["premium_jusqu_au"] == attendu


def test_paiement_refuse(client):
    en_tant_que(client, 1, "agriculteur")
    client.post("/premium", data={"reference": "FAUX"})
    en_tant_que(client, 3, "client")
    client.post("/admin/paiements/1/refuser")
    assert requete("SELECT statut FROM paiements_premium WHERE id = 1")["statut"] == "refuse"
    assert requete("SELECT premium_jusqu_au FROM utilisateurs WHERE id = 1")["premium_jusqu_au"] is None


# --- Financement réservé aux Premium

def test_financement_reserve_aux_premium(client):
    en_tant_que(client, 1, "agriculteur")
    reponse = client.post("/financement/nouvelle-demande",
                          data={"objet": "Tracteur", "montant_souhaite": "500000", "description": ""})
    assert reponse.status_code == 302 and "/premium" in reponse.headers["Location"]
    assert requete("SELECT COUNT(*) AS n FROM demandes_financement")["n"] == 0
    assert client.get("/financement/contacter-offre/1").headers["Location"].endswith("/premium")

    rendre_premium(1)
    client.post("/financement/nouvelle-demande",
                data={"objet": "Tracteur", "montant_souhaite": "500000", "description": ""})
    assert requete("SELECT COUNT(*) AS n FROM demandes_financement")["n"] == 1


def test_premium_expire(client):
    rendre_premium(1, jours=-1)
    en_tant_que(client, 1, "agriculteur")
    assert client.get("/financement/nouvelle-demande").status_code == 302


# --- Mise en avant des annonces Premium

def test_annonces_premium_en_premier_avec_badge(client):
    en_tant_que(client, 2, "client")
    page = client.get("/espace-client").get_data(as_text=True)
    assert "⭐ Pro" not in page
    rendre_premium(4)  # Moussa (Arachide), publiée en dernier
    page = client.get("/espace-client").get_data(as_text=True)
    assert "⭐ Pro" in page
    assert page.index("Arachide") < page.index("Mil")
