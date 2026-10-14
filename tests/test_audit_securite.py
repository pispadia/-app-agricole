import pytest

import database
import wave
from app import app
from routes import comptes
from tests.test_paiement_wave import FauxWave


@pytest.fixture
def emails(monkeypatch):
    envoyes = []
    monkeypatch.setattr(comptes, "envoyer_email", lambda dest, sujet, html: envoyes.append(dest) or True)
    return envoyes


@pytest.fixture
def client(tmp_path, monkeypatch, emails):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    client = app.test_client()
    client.post("/inscription", data={"nom": "Awa", "email": "a@x.sn", "mot_de_passe": "motdepasse", "role": "agriculteur"})
    emails.clear()
    return client


def test_entetes_de_securite_et_cookie(client):
    reponse = client.get("/")
    assert reponse.headers["X-Frame-Options"] == "DENY"
    assert reponse.headers["X-Content-Type-Options"] == "nosniff"
    assert reponse.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    reponse = client.post("/connexion", data={"email": "a@x.sn", "mot_de_passe": "motdepasse"})
    cookie = reponse.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie


def test_envoi_trop_gros_refuse(client):
    reponse = client.post("/connexion", data={"email": "x" * (10 * 1024 * 1024)})
    assert reponse.status_code == 302


def test_reinitialisation_limitee_par_adresse(client, emails):
    for _ in range(5):
        page = client.post("/mot-de-passe-oublie", data={"email": "a@x.sn"}, follow_redirects=True)
    assert len(emails) == comptes.MAX_LIENS_PAR_EMAIL
    assert "Si un compte existe" in page.get_data(as_text=True)  # même message, rien ne fuit


def test_confirmation_limitee(client, emails):
    client.post("/connexion", data={"email": "a@x.sn", "mot_de_passe": "motdepasse"})
    for _ in range(5):
        page = client.post("/confirmer-email", follow_redirects=True)
    assert len(emails) == comptes.MAX_LIENS_PAR_EMAIL
    assert "réessaie dans une heure" in page.get_data(as_text=True)


def test_inscriptions_limitees_par_ip(client, monkeypatch):
    monkeypatch.setattr(comptes, "MAX_INSCRIPTIONS_PAR_IP", 2)
    for i in range(3):
        page = client.post("/inscription", data={"nom": "N", "email": f"n{i}@x.sn", "mot_de_passe": "motdepasse",
                                                 "role": "client"}, follow_redirects=True)
    assert "Trop de comptes créés" in page.get_data(as_text=True)
    connexion = database.get_connexion()
    assert connexion.execute("SELECT COUNT(*) AS n FROM utilisateurs").fetchone()["n"] == 2  # Awa (déjà comptée) + 1
    connexion.close()


def test_lien_erreur_wave_ne_perd_pas_un_paiement(client, monkeypatch):
    faux = FauxWave()
    monkeypatch.setenv("WAVE_API_KEY", "test")
    monkeypatch.setattr(wave, "creer_session", faux.creer_session)
    monkeypatch.setattr(wave, "session_payee", faux.session_payee)
    client.post("/connexion", data={"email": "a@x.sn", "mot_de_passe": "motdepasse"})
    client.post("/paiement/wave/premium")
    faux.payees.add("cos-1")
    page = client.get("/paiement/wave/erreur/1", follow_redirects=True).get_data(as_text=True)
    assert "Paiement Wave reçu" in page
    connexion = database.get_connexion()
    assert connexion.execute("SELECT statut FROM paiements_wave WHERE id = 1").fetchone()["statut"] == "paye"
    connexion.close()


def test_coordonnees_masquees_dans_la_description(client):
    client.post("/connexion", data={"email": "a@x.sn", "mot_de_passe": "motdepasse"})
    client.post("/espace-agriculteur/nouvelle-recolte", data={
        "nom": "Mil", "quantite": "10 kg", "prix": "500 FCFA / kg", "date_disponibilite": "2026-11-01",
        "localite": "Thiès", "description": "Appelez-moi au 77 123 45 67"})
    connexion = database.get_connexion()
    assert connexion.execute("SELECT description FROM recoltes").fetchone()["description"] == "Appelez-moi au [numéro masqué]"
    connexion.close()
