"""Notifications push (Web Push) : alertes gratuites sur le téléphone, via l'application
installée ou le navigateur, à la place des SMS payants.

Implémente le chiffrement des messages (RFC 8291, aes128gcm) et l'identification du
serveur (VAPID, RFC 8292) avec la bibliothèque cryptography. Les clés VAPID sont créées
automatiquement au premier usage et gardées dans la base (table parametres) : rien à
configurer. Un utilisateur sans notification active reçoit un SMS, comme avant.
"""
import base64
import json
import os
import struct
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

import sms
from database import get_connexion

# Services de push des navigateurs (Chrome/Android, Firefox, Safari/iPhone, Edge) : le
# serveur n'envoie jamais de requête vers une autre adresse fournie par un utilisateur
SERVICES_PUSH = ("fcm.googleapis.com", "push.services.mozilla.com", "push.apple.com", "notify.windows.com")
DUREE_VIE = 24 * 3600  # le service de push garde le message 24 h si le téléphone est éteint


def b64url(donnees):
    return base64.urlsafe_b64encode(donnees).rstrip(b"=").decode()


def depuis_b64url(texte):
    return base64.urlsafe_b64decode(texte + "=" * (-len(texte) % 4))


def octets_publics(cle_publique):
    return cle_publique.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def cle_vapid():
    """Clé privée VAPID du serveur, créée et enregistrée au premier appel."""
    connexion_bd = get_connexion()
    ligne = connexion_bd.execute("SELECT valeur FROM parametres WHERE cle = 'vapid_privee'").fetchone()
    if ligne is None:
        nouvelle = ec.generate_private_key(ec.SECP256R1()).private_numbers().private_value
        # Si deux processus la créent en même temps, la première enregistrée gagne
        connexion_bd.execute(
            "INSERT INTO parametres (cle, valeur) VALUES ('vapid_privee', ?) ON CONFLICT (cle) DO NOTHING",
            (b64url(nouvelle.to_bytes(32, "big")),))
        connexion_bd.commit()
        ligne = connexion_bd.execute("SELECT valeur FROM parametres WHERE cle = 'vapid_privee'").fetchone()
    connexion_bd.close()
    return ec.derive_private_key(int.from_bytes(depuis_b64url(ligne["valeur"]), "big"), ec.SECP256R1())


def cle_publique_vapid():
    """Clé publique à donner au navigateur pour s'abonner (base64url)."""
    return b64url(octets_publics(cle_vapid().public_key()))


def endpoint_autorise(endpoint):
    adresse = urlparse(endpoint or "")
    hote = adresse.hostname or ""
    return adresse.scheme == "https" and any(hote == s or hote.endswith("." + s) for s in SERVICES_PUSH)


def entete_vapid(endpoint, cle_privee):
    adresse = urlparse(endpoint)
    expediteur = os.environ.get("EMAIL_EXPEDITEUR") or "contact@app-agricole.sn"
    entete = b64url(json.dumps({"typ": "JWT", "alg": "ES256"}).encode())
    revendications = b64url(json.dumps({
        "aud": f"{adresse.scheme}://{adresse.netloc}",
        "exp": int(time.time()) + 12 * 3600,
        "sub": f"mailto:{expediteur}",
    }).encode())
    a_signer = f"{entete}.{revendications}".encode()
    r, s = decode_dss_signature(cle_privee.sign(a_signer, ec.ECDSA(hashes.SHA256())))
    signature = b64url(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return f"vapid t={entete}.{revendications}.{signature}, k={b64url(octets_publics(cle_privee.public_key()))}"


def chiffrer(contenu, p256dh, auth):
    """Chiffre le message pour un navigateur (RFC 8291, un seul bloc aes128gcm)."""
    cle_navigateur = depuis_b64url(p256dh)
    secret_auth = depuis_b64url(auth)
    cle_ephemere = ec.generate_private_key(ec.SECP256R1())
    publique_ephemere = octets_publics(cle_ephemere.public_key())
    secret_partage = cle_ephemere.exchange(
        ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), cle_navigateur))

    ikm = HKDF(algorithm=hashes.SHA256(), length=32, salt=secret_auth,
               info=b"WebPush: info\x00" + cle_navigateur + publique_ephemere).derive(secret_partage)
    sel = os.urandom(16)
    cle_contenu = HKDF(algorithm=hashes.SHA256(), length=16, salt=sel,
                       info=b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(algorithm=hashes.SHA256(), length=12, salt=sel,
                 info=b"Content-Encoding: nonce\x00").derive(ikm)
    chiffre = AESGCM(cle_contenu).encrypt(nonce, contenu + b"\x02", None)  # \x02 : dernier bloc
    return sel + struct.pack("!IB", 4096, len(publique_ephemere)) + publique_ephemere + chiffre


def envoyer_push(abonnement, donnees, cle_privee):
    """Envoie une notification à un appareil. Retourne 'ok', 'expire' (abonnement à supprimer) ou 'echec'."""
    if not endpoint_autorise(abonnement["endpoint"]):
        return "expire"
    try:
        requete = urllib.request.Request(
            abonnement["endpoint"],
            data=chiffrer(json.dumps(donnees).encode(), abonnement["p256dh"], abonnement["auth"]),
            headers={"Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream",
                     "TTL": str(DUREE_VIE), "Urgency": "high",
                     "Authorization": entete_vapid(abonnement["endpoint"], cle_privee)},
            method="POST",
        )
        with urllib.request.urlopen(requete, timeout=10) as reponse:
            return "ok" if 200 <= reponse.status < 300 else "echec"
    except urllib.error.HTTPError as erreur:
        # 404/410 : l'utilisateur a désactivé les notifications ou désinstallé l'app
        return "expire" if erreur.code in (404, 410) else "echec"
    except Exception as erreur:
        print(f"[push] Échec de l'envoi : {erreur}")
        return "echec"


def abonnements_de(utilisateur_id):
    connexion_bd = get_connexion()
    lignes = connexion_bd.execute(
        "SELECT id, endpoint, p256dh, auth FROM abonnements_push WHERE utilisateur_id = ?",
        (utilisateur_id,)).fetchall()
    connexion_bd.close()
    return [dict(ligne) for ligne in lignes]


def _envoyer_a_tous(abonnements, donnees, telephone, message_sms):
    cle_privee = cle_vapid()
    resultats = {a["id"]: envoyer_push(a, donnees, cle_privee) for a in abonnements}
    expires = [i for i, r in resultats.items() if r == "expire"]
    if expires:
        connexion_bd = get_connexion()
        for abonnement_id in expires:
            connexion_bd.execute("DELETE FROM abonnements_push WHERE id = ?", (abonnement_id,))
        connexion_bd.commit()
        connexion_bd.close()
    # Aucun appareil n'a reçu la notification : on se rabat sur le SMS
    if "ok" not in resultats.values() and telephone:
        sms.envoyer_sms(telephone, message_sms)


def alerter(utilisateur_id, telephone, message, url="/"):
    """Prévient un utilisateur : notification push gratuite s'il l'a activée, sinon SMS.
    `message` est le texte du SMS (« App Agricole : ... »)."""
    abonnements = abonnements_de(utilisateur_id) if utilisateur_id else []
    if not abonnements:
        sms.alerter(telephone, message)
        return
    texte = message.removeprefix("App Agricole : ")
    donnees = {"titre": "App Agricole", "texte": texte, "url": url}
    threading.Thread(target=_envoyer_a_tous, args=(abonnements, donnees, telephone, message), daemon=True).start()
