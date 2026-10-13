"""Alertes SMS via l'API SMS d'Orange (Sonatel), https://developer.orange.com.

Variables d'environnement :
- ORANGE_SMS_CLIENT_ID et ORANGE_SMS_CLIENT_SECRET : identifiants de l'application Orange Developer ;
- ORANGE_SMS_EXPEDITEUR : numéro du compte SMS (ex: 221771234567).
Sans ces variables (en local par exemple), le SMS est affiché dans la console.
Un SMS qui échoue n'empêche jamais l'action de l'utilisateur d'aboutir.
"""
import base64
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request

URL_JETON = "https://api.orange.com/oauth/v3/token"
URL_ENVOI = "https://api.orange.com/smsmessaging/v1/outbound/{expediteur}/requests"
LONGUEUR_MAX = 160  # un seul SMS

_jeton = {"valeur": None, "expire_a": 0}


def sms_actif():
    return all(os.environ.get(nom) for nom in
               ("ORANGE_SMS_CLIENT_ID", "ORANGE_SMS_CLIENT_SECRET", "ORANGE_SMS_EXPEDITEUR"))


def numero_international(telephone):
    """'77 123 45 67' -> 'tel:+221771234567'. Retourne None si le numéro est inutilisable."""
    chiffres = re.sub(r"\D", "", telephone or "")
    if chiffres.startswith("00"):
        chiffres = chiffres[2:]
    if len(chiffres) == 9 and chiffres.startswith("7"):
        chiffres = "221" + chiffres
    if not 10 <= len(chiffres) <= 15:
        return None
    return f"tel:+{chiffres}"


def _obtenir_jeton():
    if _jeton["valeur"] and time.time() < _jeton["expire_a"]:
        return _jeton["valeur"]
    identifiants = f"{os.environ['ORANGE_SMS_CLIENT_ID']}:{os.environ['ORANGE_SMS_CLIENT_SECRET']}"
    requete = urllib.request.Request(
        URL_JETON,
        data=b"grant_type=client_credentials",
        headers={
            "Authorization": "Basic " + base64.b64encode(identifiants.encode()).decode(),
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(requete, timeout=10) as reponse:
        donnees = json.loads(reponse.read().decode("utf-8"))
    _jeton["valeur"] = donnees["access_token"]
    # Marge d'une minute avant l'expiration annoncée
    _jeton["expire_a"] = time.time() + int(donnees.get("expires_in", 3600)) - 60
    return _jeton["valeur"]


def envoyer_sms(telephone, message):
    """Envoie un SMS. Retourne True si l'envoi a réussi."""
    destinataire = numero_international(telephone)
    if destinataire is None:
        return False
    message = message[:LONGUEUR_MAX]
    if not sms_actif():
        print(f"[sms] Envoi non configuré, SMS pour {destinataire} : {message}")
        return False

    expediteur = numero_international(os.environ["ORANGE_SMS_EXPEDITEUR"])
    try:
        requete = urllib.request.Request(
            URL_ENVOI.format(expediteur=urllib.parse.quote(expediteur, safe="")),
            data=json.dumps({"outboundSMSMessageRequest": {
                "address": destinataire,
                "senderAddress": expediteur,
                "outboundSMSTextMessage": {"message": message},
            }}).encode("utf-8"),
            headers={"Authorization": f"Bearer {_obtenir_jeton()}",
                     "Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(requete, timeout=10) as reponse:
            return 200 <= reponse.status < 300
    except Exception as erreur:
        print(f"[sms] Échec de l'envoi à {destinataire} : {erreur}")
        return False


def alerter(telephone, message):
    """Envoie un SMS en arrière-plan, sans faire attendre l'utilisateur. Sans numéro, ne fait rien."""
    if not telephone:
        return
    threading.Thread(target=envoyer_sms, args=(telephone, message), daemon=True).start()
