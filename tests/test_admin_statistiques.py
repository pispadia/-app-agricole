from datetime import date

import pytest

import core
import database
from app import app

LIEU = {"pays": "SN", "region": "Dakar", "departement": "Dakar", "commune": "Yoff"}  # adresse demandée à l'inscription


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    monkeypatch.setattr(core, "EMAILS_ADMIN", {"admin@x.sn"})
    client = app.test_client()
    for nom, email, role in (("Admin", "admin@x.sn", "client"), ("Fatou", "f@x.sn", "agriculteur")):
        client.post("/inscription", data={**LIEU, "nom": nom, "email": email, "mot_de_passe": "motdepasse", "role": role})
    connexion = database.get_connexion()
    connexion.execute("UPDATE utilisateurs SET email_confirme = email WHERE email = 'admin@x.sn'")
    connexion.execute(
        """INSERT INTO recoltes (agriculteur_id, nom, quantite, prix, date_disponibilite, localite)
           VALUES (2, 'Mil', '100 kg', '500 FCFA / kg', '2026-01-01', 'Thiès')""")
    connexion.execute(
        """INSERT INTO commandes (recolte_id, client_id, quantite_demandee, statut, montant, commission)
           VALUES (1, 1, '10 kg', 'livree', 5000, 250)""")
    connexion.execute(
        """INSERT INTO commandes (recolte_id, client_id, quantite_demandee, statut, montant, commission)
           VALUES (1, 1, '5 kg', 'annulee', 2500, 125)""")
    connexion.execute(
        """INSERT INTO paiements_premium (utilisateur_id, montant, reference, statut)
           VALUES (2, 2000, 'REF1', 'valide')""")
    connexion.commit()
    connexion.close()
    return client


def connecter(client, utilisateur_id, role):
    with client.session_transaction() as session:
        session.update(utilisateur_id=utilisateur_id, nom="Test", role=role)


def test_inscription_datee(client):
    connexion = database.get_connexion()
    dates = [ligne["date_inscription"] for ligne in connexion.execute("SELECT date_inscription FROM utilisateurs")]
    connexion.close()
    assert dates == [date.today().isoformat()] * 2


def test_statistiques_admin(client):
    connecter(client, 1, "client")
    assert "/admin/statistiques" in client.get("/admin").get_data(as_text=True)
    page = client.get("/admin/statistiques").get_data(as_text=True)
    assert "<strong>2</strong> inscriptions" in page
    assert "Ventes livrées : <strong>5000 FCFA</strong>" in page
    assert "revenus de la plateforme : <strong>2250 FCFA</strong>" in page  # 250 de commission + 2000 Premium
    assert "taux de livraison : <strong>50 %</strong>" in page
    assert "<td>Mil</td><td>1</td><td>5000 FCFA</td>" in page
    assert "<td>Thiès</td>" in page and "<td>Fatou</td>" in page


def test_statistiques_reservees_a_l_admin(client):
    connecter(client, 2, "agriculteur")
    reponse = client.get("/admin/statistiques")
    assert reponse.status_code == 302 and "/admin/statistiques" not in reponse.headers["Location"]
