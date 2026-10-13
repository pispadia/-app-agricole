from datetime import date, timedelta

import pytest

import core
import database
import wave
from app import app


class FauxWave:
    """Remplace l'API Wave : enregistre les sessions créées et l'état de paiement de chacune."""

    def __init__(self):
        self.sessions = {}
        self.payees = set()

    def creer_session(self, montant, reference, url_succes, url_erreur):
        id_session = f"cos-{len(self.sessions) + 1}"
        self.sessions[id_session] = {"montant": montant, "reference": reference, "succes": url_succes}
        return id_session, f"https://pay.wave.com/c/{id_session}"

    def session_payee(self, id_session, montant_attendu):
        return id_session in self.payees and self.sessions[id_session]["montant"] == montant_attendu


@pytest.fixture
def faux_wave(monkeypatch):
    faux = FauxWave()
    monkeypatch.setenv("WAVE_API_KEY", "test")
    monkeypatch.setattr(wave, "creer_session", faux.creer_session)
    monkeypatch.setattr(wave, "session_payee", faux.session_payee)
    return faux


@pytest.fixture
def client(tmp_path, monkeypatch, faux_wave):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    connexion = database.get_connexion()
    for nom, email, role in (("Fatou", "f@x.sn", "agriculteur"), ("Awa", "a@x.sn", "client")):
        connexion.execute("INSERT INTO utilisateurs (nom, email, mot_de_passe, role) VALUES (?, ?, ?, ?)",
                          (nom, email, "x", role))
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


def test_premium_paye_avec_wave(client, faux_wave):
    en_tant_que(client, 1, "agriculteur")
    reponse = client.post("/paiement/wave/premium")
    assert reponse.status_code == 302
    assert reponse.headers["Location"] == "https://pay.wave.com/c/cos-1"
    assert faux_wave.sessions["cos-1"]["montant"] == core.PRIX_PREMIUM_MENSUEL

    # Retour sur le site avant que Wave confirme : rien n'est activé
    client.get("/paiement/wave/retour/1")
    assert ligne("SELECT premium_jusqu_au FROM utilisateurs WHERE id = 1")["premium_jusqu_au"] is None

    faux_wave.payees.add("cos-1")
    page = client.get("/paiement/wave/retour/1", follow_redirects=True).get_data(as_text=True)
    assert "Premium est actif" in page
    attendu = (date.today() + timedelta(days=core.DUREE_PREMIUM_JOURS)).isoformat()
    assert ligne("SELECT premium_jusqu_au FROM utilisateurs WHERE id = 1")["premium_jusqu_au"] == attendu
    assert ligne("SELECT COUNT(*) AS n FROM paiements_premium WHERE statut = 'valide'")["n"] == 1

    # Revenir une seconde fois ne prolonge pas l'abonnement deux fois
    client.get("/paiement/wave/retour/1")
    assert ligne("SELECT premium_jusqu_au FROM utilisateurs WHERE id = 1")["premium_jusqu_au"] == attendu
    assert ligne("SELECT COUNT(*) AS n FROM paiements_premium")["n"] == 1


def test_paiement_rattrape_sans_retour_sur_le_site(client, faux_wave):
    en_tant_que(client, 1, "agriculteur")
    client.post("/paiement/wave/premium")
    faux_wave.payees.add("cos-1")
    client.get("/premium")  # l'utilisateur revient plus tard, sans passer par le lien de retour
    assert ligne("SELECT statut FROM paiements_wave WHERE id = 1")["statut"] == "paye"


def test_retour_d_un_autre_utilisateur_refuse(client, faux_wave):
    en_tant_que(client, 1, "agriculteur")
    client.post("/paiement/wave/premium")
    faux_wave.payees.add("cos-1")
    en_tant_que(client, 2, "client")
    client.get("/paiement/wave/retour/1")
    assert ligne("SELECT statut FROM paiements_wave WHERE id = 1")["statut"] == "en_attente"
    assert ligne("SELECT premium_jusqu_au FROM utilisateurs WHERE id = 2")["premium_jusqu_au"] is None


def test_paiement_echoue(client, faux_wave):
    en_tant_que(client, 1, "agriculteur")
    client.post("/paiement/wave/premium")
    page = client.get("/paiement/wave/erreur/1", follow_redirects=True).get_data(as_text=True)
    assert "pas abouti" in page
    assert ligne("SELECT statut FROM paiements_wave WHERE id = 1")["statut"] == "echec"


def test_commissions_payees_avec_wave(client, faux_wave):
    connexion = database.get_connexion()
    connexion.execute(
        """INSERT INTO recoltes (agriculteur_id, nom, quantite, prix, date_disponibilite, localite)
           VALUES (1, 'Mil', '100 kg', '500 FCFA / kg', '2026-11-01', 'Thiès')""")
    for montant in (20000, 10000):
        connexion.execute(
            """INSERT INTO commandes (recolte_id, client_id, quantite_demandee, statut, montant, commission)
               VALUES (1, 2, '10 kg', 'livree', ?, ?)""", (montant, round(montant * core.TAUX_COMMISSION)))
    connexion.commit()
    connexion.close()

    en_tant_que(client, 1, "agriculteur")
    assert "Payer 1500 FCFA avec Wave" in client.get("/espace-agriculteur/commandes").get_data(as_text=True)
    client.post("/paiement/wave/commissions")
    assert faux_wave.sessions["cos-1"]["montant"] == 1500
    faux_wave.payees.add("cos-1")
    client.get("/paiement/wave/retour/1")
    assert ligne("SELECT COUNT(*) AS n FROM commandes WHERE commission_payee = 1")["n"] == 2


def test_bouton_wave_absent_sans_cle(client, monkeypatch):
    monkeypatch.delenv("WAVE_API_KEY")
    en_tant_que(client, 1, "agriculteur")
    assert "avec Wave" not in client.get("/premium").get_data(as_text=True)
    assert client.post("/paiement/wave/premium").headers["Location"].endswith("/premium")
