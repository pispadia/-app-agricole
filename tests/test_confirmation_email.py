import re

import pytest

import core
import database
from app import app
from routes import comptes

LIEU = {"pays": "SN", "region": "Dakar", "departement": "Dakar", "commune": "Yoff"}  # adresse demandée à l'inscription


@pytest.fixture
def emails(monkeypatch):
    envoyes = []
    monkeypatch.setattr(comptes, "envoyer_email",
                        lambda destinataire, sujet, html: envoyes.append((destinataire, html)) or True)
    return envoyes


@pytest.fixture
def client(tmp_path, monkeypatch, emails):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    monkeypatch.setattr(core, "EMAILS_ADMIN", {"chef@exemple.sn"})
    return app.test_client()


def inscrire(client, email="chef@exemple.sn"):
    client.post("/inscription", data={**LIEU, "nom": "Chef", "email": email, "mot_de_passe": "motdepasse",
                                      "role": "client"})
    client.post("/connexion", data={"email": email, "mot_de_passe": "motdepasse"})


def chemin_du_lien(emails):
    return re.search(r'href="([^"]+)"', emails[-1][1]).group(1).replace("http://localhost", "")


def test_admin_non_confirme_n_a_pas_acces(client, emails):
    inscrire(client)
    assert emails[0][0] == "chef@exemple.sn"  # lien envoyé à l'inscription
    reponse = client.get("/admin", follow_redirects=True)
    assert "Confirme ton adresse e-mail" in reponse.get_data(as_text=True)
    assert reponse.request.path == "/mon-profil"


def test_admin_confirme_a_acces(client, emails):
    inscrire(client)
    page = client.get(chemin_du_lien(emails), follow_redirects=True).get_data(as_text=True)
    assert "Adresse e-mail confirmée" in page
    assert client.get("/admin").status_code == 200
    assert "✓ Adresse e-mail confirmée" in client.get("/mon-profil").get_data(as_text=True)


def test_changer_d_email_retire_la_confirmation(client, emails):
    # Un utilisateur confirmé qui prend une adresse admin via son profil n'est pas admin
    inscrire(client, email="awa@exemple.sn")
    client.get(chemin_du_lien(emails))
    client.post("/mon-profil", data={"pays": "SN", "region": "Dakar", "departement": "Dakar", "commune": "Yoff", "nom": "Awa", "email": "chef@exemple.sn",
                                     "mot_de_passe_actuel": "motdepasse"})
    assert emails[-1][0] == "chef@exemple.sn"  # le lien part vers la nouvelle adresse
    assert client.get("/admin").status_code == 302


def test_ancien_lien_inutilisable_apres_changement_d_email(client, emails):
    inscrire(client, email="awa@exemple.sn")
    ancien_lien = chemin_du_lien(emails)
    client.post("/mon-profil", data={"pays": "SN", "region": "Dakar", "departement": "Dakar", "commune": "Yoff", "nom": "Awa", "email": "chef@exemple.sn",
                                     "mot_de_passe_actuel": "motdepasse"})
    page = client.get(ancien_lien, follow_redirects=True).get_data(as_text=True)
    assert "ne correspond plus" in page
    assert client.get("/admin").status_code == 302


def test_lien_falsifie(client, emails):
    inscrire(client)
    page = client.get(chemin_du_lien(emails) + "x", follow_redirects=True).get_data(as_text=True)
    assert "invalide ou a expiré" in page
    assert client.get("/admin").status_code == 302


def test_renvoyer_le_lien(client, emails):
    inscrire(client)
    page = client.post("/confirmer-email", follow_redirects=True).get_data(as_text=True)
    assert "Un lien de confirmation a été envoyé" in page and len(emails) == 2
    client.get(chemin_du_lien(emails))
    page = client.post("/confirmer-email", follow_redirects=True).get_data(as_text=True)
    assert "déjà confirmée" in page and len(emails) == 2
