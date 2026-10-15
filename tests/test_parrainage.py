from datetime import date, timedelta

import pytest

import core
import database
import sms
from app import app
from routes import parrainage

LIEU = {"pays": "SN", "region": "Dakar", "departement": "Dakar", "commune": "Yoff"}  # adresse demandée à l'inscription


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    monkeypatch.setattr(sms, "alerter", lambda *args: None)
    monkeypatch.setattr(core, "EMAILS_ADMIN", {"admin@x.sn"})
    connexion = database.get_connexion()
    # 1 Parrain (client), 2 Fatou (agriculteur, filleule), 3 Awa (cliente), 4 Admin
    for nom, email, role in (("Parrain", "p@x.sn", "client"), ("Fatou", "f@x.sn", "agriculteur"),
                             ("Awa", "a@x.sn", "client"), ("Admin", "admin@x.sn", "client")):
        connexion.execute("INSERT INTO utilisateurs (nom, email, mot_de_passe, role, email_confirme) "
                          "VALUES (?, ?, 'x', ?, ?)", (nom, email, role, email))
    connexion.execute("UPDATE utilisateurs SET parrain_id = 1 WHERE id = 2")
    connexion.execute(
        """INSERT INTO recoltes (agriculteur_id, nom, quantite, prix, date_disponibilite, localite)
           VALUES (2, 'Mil', '100 kg', '500 FCFA / kg', '2026-11-01', 'Thiès')""")
    connexion.commit()
    connexion.close()
    return app.test_client()


def en_tant_que(client, utilisateur_id, role):
    with client.session_transaction() as session:
        session.update(utilisateur_id=utilisateur_id, nom="Test", role=role)


def ligne(sql, parametres=()):
    connexion = database.get_connexion()
    resultat = connexion.execute(sql, parametres).fetchone()
    connexion.close()
    return resultat


def vente(client, montant, client_id=3):
    connexion = database.get_connexion()
    commande_id = connexion.execute(
        "INSERT INTO commandes (recolte_id, client_id, quantite_demandee, statut) VALUES (1, ?, '5 kg', 'confirmee') RETURNING id",
        (client_id,)).fetchone()["id"]
    connexion.commit()
    connexion.close()
    en_tant_que(client, 2, "agriculteur")
    client.post(f"/espace-agriculteur/commandes/{commande_id}/statut", data={"statut": "livree", "montant": str(montant)})
    return commande_id


def commission_reglee(client, commande_id):
    en_tant_que(client, 4, "client")
    client.post(f"/admin/commissions/{commande_id}/reglee")


def premium_parrain():
    return ligne("SELECT premium_jusqu_au FROM utilisateurs WHERE id = 1")["premium_jusqu_au"]


def test_inscription_avec_le_lien(client):
    en_tant_que(client, 1, "client")
    page = client.get("/parrainage").get_data(as_text=True)
    code = ligne("SELECT code_parrainage FROM utilisateurs WHERE id = 1")["code_parrainage"]
    assert len(code) == 8 and f"parrain={code}" in page and "wa.me" in page
    nouveau = app.test_client()
    nouveau.get(f"/inscription?parrain={code.lower()}")
    nouveau.post("/inscription", data={**LIEU, "nom": "Ibou", "email": "i@x.sn", "mot_de_passe": "motdepasse", "role": "client"})
    assert ligne("SELECT parrain_id FROM utilisateurs WHERE email = 'i@x.sn'")["parrain_id"] == 1


def test_recompense_apres_vente_et_commission_reglee(client):
    commande_id = vente(client, 10000)
    assert premium_parrain() is None  # commission pas encore réglée
    commission_reglee(client, commande_id)
    assert premium_parrain() == (date.today() + timedelta(days=30)).isoformat()
    assert ligne("SELECT parrainage_recompense_le FROM utilisateurs WHERE id = 2")[0] == date.today().isoformat()
    # Une seule récompense par filleul
    commission_reglee(client, vente(client, 20000))
    assert premium_parrain() == (date.today() + timedelta(days=30)).isoformat()
    en_tant_que(client, 1, "client")
    assert "1 mois gagné" in client.get("/parrainage").get_data(as_text=True)


def test_pas_de_recompense_pour_petite_vente(client):
    commission_reglee(client, vente(client, parrainage.MONTANT_MINIMUM - 1))
    assert premium_parrain() is None


def test_pas_de_recompense_si_le_parrain_achete_lui_meme(client):
    # Le parrain crée sa filleule puis lui achète : pas de Premium gratuit
    commission_reglee(client, vente(client, 10000, client_id=1))
    assert premium_parrain() is None


def test_plafond_annuel(client, monkeypatch):
    monkeypatch.setattr(parrainage, "MAX_RECOMPENSES_PAR_AN", 0)
    commission_reglee(client, vente(client, 10000))
    assert premium_parrain() is None
