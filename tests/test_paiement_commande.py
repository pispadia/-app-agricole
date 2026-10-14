import pytest

import core
import database
import sms
from app import app
from tests.test_paiement_wave import FauxWave
import wave


@pytest.fixture
def faux_wave(monkeypatch):
    faux = FauxWave()
    monkeypatch.setenv("WAVE_API_KEY", "test")
    monkeypatch.setattr(wave, "creer_session", faux.creer_session)
    monkeypatch.setattr(wave, "session_payee", faux.session_payee)
    return faux


@pytest.fixture
def envoyes(monkeypatch):
    liste = []
    monkeypatch.setattr(sms, "alerter", lambda telephone, message: liste.append(message))
    return liste


@pytest.fixture
def client(tmp_path, monkeypatch, faux_wave, envoyes):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    monkeypatch.setattr(core, "EMAILS_ADMIN", {"admin@x.sn"})
    connexion = database.get_connexion()
    for nom, email, role in (("Fatou", "f@x.sn", "agriculteur"), ("Awa", "a@x.sn", "client"),
                             ("Admin", "admin@x.sn", "client"), ("Ibou", "i@x.sn", "client")):
        connexion.execute("INSERT INTO utilisateurs (nom, email, mot_de_passe, role, email_confirme) "
                          "VALUES (?, ?, 'x', ?, ?)", (nom, email, role, email))
    connexion.execute(
        """INSERT INTO recoltes (agriculteur_id, nom, quantite, prix, date_disponibilite, localite)
           VALUES (1, 'Mil', '100 kg', '500 FCFA / kg', '2026-11-01', 'Thiès')""")
    connexion.commit()
    connexion.close()
    return app.test_client()


def en_tant_que(client, utilisateur_id, role):
    with client.session_transaction() as session:
        session.update(utilisateur_id=utilisateur_id, nom="Test", role=role)


def commande(commande_id=1):
    connexion = database.get_connexion()
    ligne = connexion.execute("SELECT * FROM commandes WHERE id = ?", (commande_id,)).fetchone()
    connexion.close()
    return ligne


def commander_et_confirmer(client, montant="10000", frais="1000"):
    en_tant_que(client, 2, "client")
    client.post("/commander/1", data={"quantite_demandee": "20 kg", "mode_paiement": "wave",
                                      "mode_livraison": "livraison", "adresse_livraison": "Médina"})
    en_tant_que(client, 1, "agriculteur")
    client.post("/espace-agriculteur/commandes/1/statut",
                data={"statut": "confirmee", "montant": montant, "frais_livraison": frais})


def payer(client, faux_wave):
    en_tant_que(client, 2, "client")
    reponse = client.post("/paiement/wave/commande/1")
    id_session = reponse.headers["Location"].rsplit("/", 1)[1]
    faux_wave.payees.add(id_session)
    return client.get("/paiement/wave/retour/1", follow_redirects=True).get_data(as_text=True)


def test_parcours_complet_paiement_en_ligne(client, faux_wave, envoyes):
    commander_et_confirmer(client)
    c = commande()
    assert (c["mode_paiement"], c["montant"], c["commission"], c["montant_a_payer"]) == ("wave", 10000, 500, 11000)
    assert "A payer avec Wave : 11000 FCFA" in envoyes[-1]

    en_tant_que(client, 2, "client")
    assert "Payer 11000 FCFA avec Wave" in client.get("/mes-commandes").get_data(as_text=True)
    page = payer(client, faux_wave)
    assert "Ta commande est payée" in page
    assert faux_wave.sessions["cos-1"]["montant"] == 11000
    c = commande()
    assert c["paye_en_ligne"] == 1 and c["commission_payee"] == 1
    assert "payée en ligne" in envoyes[-1]

    # L'agriculteur livre sans saisir de montant ; l'admin voit ce qu'il doit lui reverser
    en_tant_que(client, 1, "agriculteur")
    assert "tu recevras 10500 FCFA" in client.get("/espace-agriculteur/commandes").get_data(as_text=True)
    client.post("/espace-agriculteur/commandes/1/statut", data={"statut": "livree"})
    assert commande()["statut"] == "livree"

    en_tant_que(client, 3, "client")
    page = client.get("/admin").get_data(as_text=True)
    assert "À envoyer par Wave : <strong>10500 FCFA" in page
    client.post("/admin/commandes/1/reversee")
    assert commande()["reverse_agriculteur"] == 1
    assert "À reverser" not in client.get("/admin").get_data(as_text=True)


def test_confirmation_exige_le_prix(client):
    commander_et_confirmer(client, montant="")
    assert commande()["statut"] == "en_attente"


def test_annulation_apres_paiement_a_rembourser(client, faux_wave):
    commander_et_confirmer(client)
    payer(client, faux_wave)
    en_tant_que(client, 1, "agriculteur")
    client.post("/espace-agriculteur/commandes/1/statut", data={"statut": "annulee"})
    en_tant_que(client, 3, "client")
    assert "à rembourser <strong>11000 FCFA" in client.get("/admin").get_data(as_text=True)
    client.post("/admin/commandes/1/remboursee")
    assert commande()["rembourse"] == 1


def test_paiement_refuse_si_pas_confirmee_ou_autre_client(client, faux_wave):
    en_tant_que(client, 2, "client")
    client.post("/commander/1", data={"quantite_demandee": "20 kg", "mode_paiement": "wave"})
    assert client.post("/paiement/wave/commande/1").headers["Location"].endswith("/mes-commandes")
    assert faux_wave.sessions == {}  # pas encore confirmée
    en_tant_que(client, 1, "agriculteur")
    client.post("/espace-agriculteur/commandes/1/statut", data={"statut": "confirmee", "montant": "5000"})
    en_tant_que(client, 4, "client")
    client.post("/paiement/wave/commande/1")
    assert faux_wave.sessions == {}  # commande d'un autre client


def test_sans_wave_paiement_a_la_livraison(client, monkeypatch):
    monkeypatch.delenv("WAVE_API_KEY")
    en_tant_que(client, 2, "client")
    assert "Paiement en ligne" not in client.get("/commander/1").get_data(as_text=True)
    client.post("/commander/1", data={"quantite_demandee": "20 kg", "mode_paiement": "wave"})
    assert commande()["mode_paiement"] == "livraison"
