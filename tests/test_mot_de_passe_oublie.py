import re

import pytest

import database
from app import app
from routes import comptes


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
    client = app.test_client()
    client.post("/inscription", data={
        "nom": "Awa", "email": "awa@exemple.sn", "mot_de_passe": "ancien-mdp", "role": "client",
    })
    return client


def demander_lien(client, emails, email="awa@exemple.sn"):
    page = client.post("/mot-de-passe-oublie", data={"email": email}, follow_redirects=True)
    return page.get_data(as_text=True)


def chemin_du_lien(emails):
    lien = re.search(r'href="([^"]+)"', emails[-1][1]).group(1)
    return lien.replace("http://localhost", "")


def peut_se_connecter(client, mot_de_passe):
    client.get("/deconnexion")
    client.post("/connexion", data={"email": "awa@exemple.sn", "mot_de_passe": mot_de_passe})
    with client.session_transaction() as session:
        return session.get("role") == "client"


def test_reinitialisation_complete(client, emails):
    assert "Si un compte existe" in demander_lien(client, emails)
    assert emails[0][0] == "awa@exemple.sn"
    chemin = chemin_du_lien(emails)
    client.post(chemin, data={"mot_de_passe": "nouveau-mdp", "confirmation": "nouveau-mdp"})
    assert peut_se_connecter(client, "nouveau-mdp")
    assert not peut_se_connecter(client, "ancien-mdp")


def test_email_inconnu_meme_message_sans_envoi(client, emails):
    assert "Si un compte existe" in demander_lien(client, emails, email="inconnu@exemple.sn")
    assert emails == []


def test_lien_utilisable_une_seule_fois(client, emails):
    demander_lien(client, emails)
    chemin = chemin_du_lien(emails)
    client.post(chemin, data={"mot_de_passe": "nouveau-mdp", "confirmation": "nouveau-mdp"})
    page = client.post(chemin, data={"mot_de_passe": "pirate-mdp", "confirmation": "pirate-mdp"},
                       follow_redirects=True).get_data(as_text=True)
    assert "invalide ou a expiré" in page
    assert peut_se_connecter(client, "nouveau-mdp")


def test_lien_falsifie_ou_expire(client, emails, monkeypatch):
    page = client.get("/reinitialiser-mot-de-passe/faux-jeton", follow_redirects=True)
    assert "invalide ou a expiré" in page.get_data(as_text=True)

    demander_lien(client, emails)
    chemin = chemin_du_lien(emails)
    monkeypatch.setattr(comptes, "DUREE_LIEN_REINITIALISATION", -1)
    page = client.get(chemin, follow_redirects=True)
    assert "invalide ou a expiré" in page.get_data(as_text=True)


def test_confirmation_differente_refusee(client, emails):
    demander_lien(client, emails)
    page = client.post(chemin_du_lien(emails), data={"mot_de_passe": "aaaaaaaa", "confirmation": "bbbbbbbb"},
                       follow_redirects=True).get_data(as_text=True)
    assert "identiques" in page
    assert peut_se_connecter(client, "ancien-mdp")
