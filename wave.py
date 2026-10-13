"""Paiement par Wave (API Checkout de Wave Business).

Variables d'environnement :
- WAVE_API_KEY : clé API du compte marchand Wave Business (Développeurs > Clés API),
  avec l'autorisation « Checkout API ».
Sans clé, le paiement Wave est désactivé et le paiement manuel reste proposé.

Principe : on crée une session de paiement, l'utilisateur paie dans l'app Wave
(wave_launch_url), puis revient sur le site ; on interroge alors Wave pour
vérifier que la session est bien payée avant d'activer quoi que ce soit.
"""
import json
import os
import urllib.request

URL_API = "https://api.wave.com/v1/checkout/sessions"


def wave_active():
    return bool(os.environ.get("WAVE_API_KEY"))


def _appel(methode, url, donnees=None):
    requete = urllib.request.Request(
        url,
        data=json.dumps(donnees).encode("utf-8") if donnees is not None else None,
        headers={"Authorization": f"Bearer {os.environ['WAVE_API_KEY']}",
                 "Content-Type": "application/json"},
        method=methode,
    )
    with urllib.request.urlopen(requete, timeout=15) as reponse:
        return json.loads(reponse.read().decode("utf-8"))


def creer_session(montant, reference, url_succes, url_erreur):
    """Crée une session de paiement de `montant` FCFA ; retourne (id de session, lien de paiement)."""
    session = _appel("POST", URL_API, {
        "amount": str(int(montant)),
        "currency": "XOF",
        "client_reference": reference,
        "success_url": url_succes,
        "error_url": url_erreur,
    })
    return session["id"], session["wave_launch_url"]


def session_payee(id_session, montant_attendu):
    """True si Wave confirme que la session est payée, pour le montant attendu."""
    session = _appel("GET", f"{URL_API}/{id_session}")
    return (session.get("payment_status") == "succeeded"
            and str(session.get("amount")) == str(int(montant_attendu))
            and session.get("currency") == "XOF")
