"""Activation des notifications push sur un appareil (téléphone ou ordinateur)."""
from flask import jsonify, request, session

import push
from database import get_connexion
from core import app, utilisateur_connecte


def abonnement_valide(donnees):
    """(endpoint, p256dh, auth) si l'abonnement envoyé par le navigateur est correct, sinon None."""
    try:
        endpoint = donnees["endpoint"]
        p256dh, auth = donnees["keys"]["p256dh"], donnees["keys"]["auth"]
        if (push.endpoint_autorise(endpoint) and len(endpoint) <= 1000
                and len(push.depuis_b64url(p256dh)) == 65 and len(push.depuis_b64url(auth)) == 16):
            return endpoint, p256dh, auth
    except (KeyError, TypeError, ValueError):
        pass
    return None


@app.route("/push/cle")
def cle_push():
    return jsonify({"cle": push.cle_publique_vapid()})


@app.route("/push/abonnement", methods=["POST"])
def abonnement_push():
    if not utilisateur_connecte():
        return jsonify({"erreur": "connexion requise"}), 401
    abonnement = abonnement_valide(request.get_json(silent=True) or {})
    if abonnement is None:
        return jsonify({"erreur": "abonnement invalide"}), 400
    endpoint, p256dh, auth = abonnement
    connexion_bd = get_connexion()
    # Un appareil ne reçoit les notifications que du dernier compte connecté dessus
    connexion_bd.execute("DELETE FROM abonnements_push WHERE endpoint = ?", (endpoint,))
    connexion_bd.execute(
        "INSERT INTO abonnements_push (utilisateur_id, endpoint, p256dh, auth) VALUES (?, ?, ?, ?)",
        (session["utilisateur_id"], endpoint, p256dh, auth))
    connexion_bd.commit()
    connexion_bd.close()
    push.alerter(session["utilisateur_id"], None,
                 "App Agricole : notifications activées sur cet appareil ✅", "/notifications")
    return jsonify({"ok": True})


@app.route("/push/desabonnement", methods=["POST"])
def desabonnement_push():
    if not utilisateur_connecte():
        return jsonify({"erreur": "connexion requise"}), 401
    endpoint = (request.get_json(silent=True) or {}).get("endpoint")
    connexion_bd = get_connexion()
    connexion_bd.execute("DELETE FROM abonnements_push WHERE endpoint = ? AND utilisateur_id = ?",
                         (endpoint, session["utilisateur_id"]))
    connexion_bd.commit()
    connexion_bd.close()
    return jsonify({"ok": True})
