"""Envoi d'e-mails via l'API de Brevo (https://www.brevo.com, offre gratuite : 300 e-mails/jour).

Variables d'environnement :
- BREVO_API_KEY : clé API Brevo (SMTP & API > Clés API) ;
- EMAIL_EXPEDITEUR : adresse d'expédition validée dans Brevo (Expéditeurs).
Sans ces variables (en local par exemple), l'e-mail est affiché dans la console.
"""
import json
import os
import urllib.request

URL_BREVO = "https://api.brevo.com/v3/smtp/email"


def envoyer_email(destinataire, sujet, contenu_html):
    """Envoie un e-mail. Retourne True si l'envoi a réussi (ou a été affiché en local)."""
    cle_api = os.environ.get("BREVO_API_KEY")
    expediteur = os.environ.get("EMAIL_EXPEDITEUR")

    if not cle_api or not expediteur:
        print(f"[email] Envoi non configuré, e-mail pour {destinataire} : {sujet}\n{contenu_html}")
        return not os.environ.get("DATABASE_URL")  # en ligne, l'absence de configuration est une erreur

    requete = urllib.request.Request(
        URL_BREVO,
        data=json.dumps({
            "sender": {"name": "App Agricole", "email": expediteur},
            "to": [{"email": destinataire}],
            "subject": sujet,
            "htmlContent": contenu_html,
        }).encode("utf-8"),
        headers={"api-key": cle_api, "Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(requete, timeout=10) as reponse:
            return 200 <= reponse.status < 300
    except Exception as erreur:
        print(f"[email] Échec de l'envoi à {destinataire} : {erreur}")
        return False
