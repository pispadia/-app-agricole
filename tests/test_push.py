import base64
import json
import os
import struct
import urllib.error

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

import database
import push
import sms
from app import app

ENDPOINT = "https://fcm.googleapis.com/fcm/send/abc123"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    connexion = database.get_connexion()
    connexion.execute("""INSERT INTO utilisateurs (nom, email, mot_de_passe, role, telephone)
                         VALUES ('Fatou', 'f@x.sn', 'x', 'agriculteur', '771234567')""")
    connexion.commit()
    connexion.close()
    return app.test_client()


class Navigateur:
    """Simule le navigateur qui reçoit et déchiffre la notification."""
    def __init__(self):
        self.cle = ec.generate_private_key(ec.SECP256R1())
        self.auth = os.urandom(16)

    def abonnement(self, endpoint=ENDPOINT):
        return {"endpoint": endpoint, "keys": {"p256dh": push.b64url(push.octets_publics(self.cle.public_key())),
                                               "auth": push.b64url(self.auth)}}

    def dechiffrer(self, corps):
        sel, taille, longueur = corps[:16], *struct.unpack("!IB", corps[16:21])
        cle_serveur = corps[21:21 + longueur]
        chiffre = corps[21 + longueur:]
        assert taille == 4096
        secret = self.cle.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), cle_serveur))
        ma_cle = push.octets_publics(self.cle.public_key())
        ikm = HKDF(hashes.SHA256(), 32, self.auth, b"WebPush: info\x00" + ma_cle + cle_serveur).derive(secret)
        cek = HKDF(hashes.SHA256(), 16, sel, b"Content-Encoding: aes128gcm\x00").derive(ikm)
        nonce = HKDF(hashes.SHA256(), 12, sel, b"Content-Encoding: nonce\x00").derive(ikm)
        clair = AESGCM(cek).decrypt(nonce, chiffre, None)
        assert clair.endswith(b"\x02")
        return json.loads(clair[:-1])


class FausseReponse:
    status = 201

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_chiffrement_et_signature_vapid(client, monkeypatch):
    navigateur = Navigateur()
    envoyees = []

    def faux_urlopen(requete, timeout):
        envoyees.append(requete)
        return FausseReponse()

    monkeypatch.setattr(push.urllib.request, "urlopen", faux_urlopen)
    cle = push.cle_vapid()
    abonnement = {"id": 1, "endpoint": ENDPOINT, **navigateur.abonnement()["keys"]}
    assert push.envoyer_push(abonnement, {"texte": "Nouvelle commande"}, cle) == "ok"

    requete = envoyees[0]
    assert requete.full_url == ENDPOINT and requete.get_header("Content-encoding") == "aes128gcm"
    assert navigateur.dechiffrer(requete.data) == {"texte": "Nouvelle commande"}

    # Jeton VAPID : signé par la clé publique annoncée, pour le bon service de push
    autorisation = requete.get_header("Authorization")
    jeton, cle_publique = autorisation.removeprefix("vapid t=").split(", k=")
    entete, revendications, signature = jeton.split(".")
    brute = push.depuis_b64url(signature)
    ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), push.depuis_b64url(cle_publique)).verify(
        encode_dss_signature(int.from_bytes(brute[:32], "big"), int.from_bytes(brute[32:], "big")),
        f"{entete}.{revendications}".encode(), ec.ECDSA(hashes.SHA256()))
    assert json.loads(push.depuis_b64url(revendications))["aud"] == "https://fcm.googleapis.com"
    assert cle_publique == push.cle_publique_vapid()  # clé gardée en base, la même à chaque fois


def test_abonnement_puis_notification_au_lieu_du_sms(client, monkeypatch):
    navigateur = Navigateur()
    with client.session_transaction() as session:
        session.update(utilisateur_id=1, nom="Fatou", role="agriculteur")
    assert client.get("/push/cle").get_json()["cle"] == push.cle_publique_vapid()

    envois, sms_envoyes = [], []
    monkeypatch.setattr(push, "_envoyer_a_tous", lambda abonnements, donnees, *a: envois.append(donnees))
    monkeypatch.setattr(push.threading, "Thread", lambda target, args, daemon: type(
        "T", (), {"start": lambda self: target(*args)})())
    monkeypatch.setattr(sms, "alerter", lambda *args: sms_envoyes.append(args))

    assert client.post("/push/abonnement", json=navigateur.abonnement()).status_code == 200
    assert envois[-1]["texte"].startswith("notifications activées")

    push.alerter(1, "771234567", "App Agricole : nouvelle commande de Mil.", "/espace-agriculteur/commandes")
    assert envois[-1] == {"titre": "App Agricole", "texte": "nouvelle commande de Mil.",
                          "url": "/espace-agriculteur/commandes"}
    assert sms_envoyes == []  # gratuit : pas de SMS

    client.post("/push/desabonnement", json={"endpoint": ENDPOINT})
    push.alerter(1, "771234567", "App Agricole : nouvelle commande de Mil.")
    assert sms_envoyes == [("771234567", "App Agricole : nouvelle commande de Mil.")]


def test_abonnement_refuse_hors_services_de_push(client):
    navigateur = Navigateur()
    with client.session_transaction() as session:
        session.update(utilisateur_id=1, nom="Fatou", role="agriculteur")
    for endpoint in ("http://fcm.googleapis.com/x", "https://exemple.com/x", "https://fcm.googleapis.com.evil.sn/x"):
        assert client.post("/push/abonnement", json=navigateur.abonnement(endpoint)).status_code == 400
    assert client.post("/push/abonnement", json={"endpoint": ENDPOINT}).status_code == 400
    with client.session_transaction() as session:
        session.clear()
    assert client.post("/push/abonnement", json=navigateur.abonnement()).status_code == 401


def test_appareil_desinstalle_supprime_et_sms_de_secours(client, monkeypatch):
    navigateur = Navigateur()
    connexion = database.get_connexion()
    keys = navigateur.abonnement()["keys"]
    connexion.execute("INSERT INTO abonnements_push (utilisateur_id, endpoint, p256dh, auth) VALUES (1, ?, ?, ?)",
                      (ENDPOINT, keys["p256dh"], keys["auth"]))
    connexion.commit()
    connexion.close()

    def expire(requete, timeout):
        raise urllib.error.HTTPError(ENDPOINT, 410, "Gone", {}, None)

    sms_envoyes = []
    monkeypatch.setattr(push.urllib.request, "urlopen", expire)
    monkeypatch.setattr(sms, "envoyer_sms", lambda *args: sms_envoyes.append(args))
    push._envoyer_a_tous(push.abonnements_de(1), {"texte": "x"}, "771234567", "App Agricole : x")
    assert push.abonnements_de(1) == []
    assert sms_envoyes == [("771234567", "App Agricole : x")]
