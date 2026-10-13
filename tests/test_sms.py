import json

import pytest

import database
import sms
from app import app


@pytest.fixture
def envoyes(monkeypatch):
    """Remplace l'envoi réel : chaque SMS est noté (telephone, message)."""
    liste = []
    monkeypatch.setattr(sms, "alerter", lambda telephone, message: telephone and liste.append((telephone, message)))
    return liste


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)

    connexion = database.get_connexion()
    for nom, email, role, telephone in (("Fatou", "f@x.sn", "agriculteur", "77 111 22 33"),
                                        ("Awa", "a@x.sn", "client", "78 444 55 66"),
                                        ("Moussa", "m@x.sn", "agriculteur", None)):
        connexion.execute(
            "INSERT INTO utilisateurs (nom, email, mot_de_passe, role, telephone) VALUES (?, ?, ?, ?, ?)",
            (nom, email, "x", role, telephone))
    for agriculteur_id, nom in ((1, "Mil"), (1, "Niébé"), (3, "Maïs")):
        connexion.execute(
            """INSERT INTO recoltes (agriculteur_id, nom, quantite, prix, date_disponibilite, localite)
               VALUES (?, ?, '100 kg', '500 FCFA / kg', '2026-11-01', 'Thiès')""", (agriculteur_id, nom))
    connexion.commit()
    connexion.close()
    return app.test_client()


def en_tant_que(client, utilisateur_id, nom, role):
    with client.session_transaction() as session:
        session.update(utilisateur_id=utilisateur_id, nom=nom, role=role)


def test_numero_international():
    assert sms.numero_international("77 123 45 67") == "tel:+221771234567"
    assert sms.numero_international("+221 77 123 45 67") == "tel:+221771234567"
    assert sms.numero_international("0033 6 12 34 56 78") == "tel:+33612345678"
    assert sms.numero_international("123") is None
    assert sms.numero_international(None) is None


def test_commande_previent_l_agriculteur(client, envoyes):
    en_tant_que(client, 2, "Awa", "client")
    client.post("/commander/1", data={"quantite_demandee": "20 kg"})
    assert envoyes == [("77 111 22 33", envoyes[0][1])]
    assert "Awa" in envoyes[0][1] and "Mil" in envoyes[0][1]


def test_panier_un_seul_sms_par_agriculteur(client, envoyes):
    en_tant_que(client, 2, "Awa", "client")
    with client.session_transaction() as session:
        session["panier"] = [{"recolte_id": i, "quantite": "5 kg"} for i in (1, 2, 3)]
    client.post("/panier/valider")
    # Fatou reçoit un SMS pour ses 2 récoltes ; Moussa n'a pas de téléphone
    assert len(envoyes) == 1
    assert envoyes[0][0] == "77 111 22 33" and "Mil, Niébé" in envoyes[0][1]


def test_changement_de_statut_previent_le_client(client, envoyes):
    en_tant_que(client, 2, "Awa", "client")
    client.post("/commander/1", data={"quantite_demandee": "20 kg"})
    en_tant_que(client, 1, "Fatou", "agriculteur")
    client.post("/espace-agriculteur/commandes/1/statut", data={"statut": "confirmee"})
    client.post("/espace-agriculteur/commandes/1/statut", data={"statut": "livree", "montant": "10000"})
    assert [t for t, _ in envoyes[1:]] == ["78 444 55 66", "78 444 55 66"]
    assert "confirmée" in envoyes[1][1] and "livrée" in envoyes[2][1]


def test_transition_refusee_n_envoie_rien(client, envoyes):
    en_tant_que(client, 2, "Awa", "client")
    client.post("/commander/1", data={"quantite_demandee": "20 kg"})
    en_tant_que(client, 1, "Fatou", "agriculteur")
    client.post("/espace-agriculteur/commandes/1/statut", data={"statut": "livree", "montant": "10000"})
    assert len(envoyes) == 1  # seulement le SMS de la commande


def test_annulation_previent_l_agriculteur(client, envoyes):
    en_tant_que(client, 2, "Awa", "client")
    client.post("/commander/1", data={"quantite_demandee": "20 kg"})
    client.post("/mes-commandes/1/annuler")
    assert envoyes[1] == ("77 111 22 33", "App Agricole : Awa a annulé sa commande de Mil.")
    client.post("/mes-commandes/1/annuler")  # déjà annulée : pas de second SMS
    assert len(envoyes) == 2


class FausseReponse:
    def __init__(self, donnees, status=201):
        self.status, self.donnees = status, donnees

    def read(self):
        return json.dumps(self.donnees).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_envoyer_sms_appelle_l_api_orange(monkeypatch):
    for nom, valeur in (("ORANGE_SMS_CLIENT_ID", "id"), ("ORANGE_SMS_CLIENT_SECRET", "secret"),
                        ("ORANGE_SMS_EXPEDITEUR", "221770000000")):
        monkeypatch.setenv(nom, valeur)
    monkeypatch.setitem(sms._jeton, "valeur", None)
    requetes = []

    def faux_urlopen(requete, timeout):
        requetes.append(requete)
        if requete.full_url == sms.URL_JETON:
            return FausseReponse({"access_token": "jeton", "expires_in": 3600}, status=200)
        return FausseReponse({})

    monkeypatch.setattr(sms.urllib.request, "urlopen", faux_urlopen)
    assert sms.envoyer_sms("77 123 45 67", "Bonjour")
    assert sms.envoyer_sms("77 123 45 67", "Encore")
    assert len(requetes) == 3  # le jeton est réutilisé
    envoi = requetes[1]
    assert envoi.full_url.endswith("/outbound/tel%3A%2B221770000000/requests")
    assert envoi.headers["Authorization"] == "Bearer jeton"
    corps = json.loads(envoi.data)["outboundSMSMessageRequest"]
    assert corps["address"] == "tel:+221771234567"
    assert corps["outboundSMSTextMessage"]["message"] == "Bonjour"


def test_envoyer_sms_sans_configuration_ou_en_erreur(monkeypatch):
    for nom in ("ORANGE_SMS_CLIENT_ID", "ORANGE_SMS_CLIENT_SECRET", "ORANGE_SMS_EXPEDITEUR"):
        monkeypatch.delenv(nom, raising=False)
    assert sms.envoyer_sms("77 123 45 67", "Bonjour") is False

    for nom in ("ORANGE_SMS_CLIENT_ID", "ORANGE_SMS_CLIENT_SECRET", "ORANGE_SMS_EXPEDITEUR"):
        monkeypatch.setenv(nom, "x")
    monkeypatch.setitem(sms._jeton, "valeur", None)

    def panne(*args, **kwargs):
        raise OSError("réseau indisponible")

    monkeypatch.setattr(sms.urllib.request, "urlopen", panne)
    assert sms.envoyer_sms("77 123 45 67", "Bonjour") is False
