"""Tâche quotidienne de rappels, déclenchée chaque matin par GitHub Actions
(.github/workflows/taches.yml) avec le jeton secret TACHES_TOKEN :
- pré-commandes : le client est prévenu le jour où la récolte réservée est prête ;
- commandes en attente depuis plus de 48 h : l'agriculteur est relancé ;
- Premium : le membre est prévenu 3 jours avant la fin de son abonnement ;
- début de mois : chaque agriculteur actif reçoit son bilan du mois passé (routes/rapport_mensuel.py).
Chaque rappel n'est envoyé qu'une fois (colonnes rappel_pret_envoye, relance_envoyee,
rappel_premium_pour). Sans TACHES_TOKEN, l'adresse n'existe pas (404)."""
import hmac
import os
import threading
from datetime import date, datetime, timedelta

from flask import abort, jsonify, request, url_for
from markupsafe import escape

import sms
from core import app, csrf
from database import get_connexion
from emails import envoyer_email
from core import date_fr

DELAI_RELANCE_HEURES = 48
JOURS_AVANT_FIN_PREMIUM = 3


def jeton_valide():
    attendu = os.environ.get("TACHES_TOKEN")
    recu = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    return bool(attendu) and hmac.compare_digest(recu, attendu)


def preparer_rappels(connexion_bd):
    """Repère les rappels à envoyer, les marque comme envoyés, et retourne la liste des messages
    (destinataire e-mail, téléphone, sujet, texte)."""
    aujourdhui = date.today().isoformat()
    messages = []

    # 1. Pré-commandes dont la récolte est prête aujourd'hui (ou depuis, si un jour a été manqué)
    for c in connexion_bd.execute(
        """SELECT commandes.id, recoltes.nom, recoltes.date_disponibilite, utilisateurs.nom AS nom_client,
                  utilisateurs.email, utilisateurs.telephone
           FROM commandes JOIN recoltes ON commandes.recolte_id = recoltes.id
           JOIN utilisateurs ON commandes.client_id = utilisateurs.id
           WHERE commandes.statut IN ('en_attente', 'confirmee') AND commandes.rappel_pret_envoye = 0
             AND recoltes.date_disponibilite <= ? AND SUBSTR(commandes.date_creation, 1, 10) < recoltes.date_disponibilite""",
        (aujourdhui,)
    ).fetchall():
        connexion_bd.execute("UPDATE commandes SET rappel_pret_envoye = 1 WHERE id = ?", (c["id"],))
        texte = f"La récolte que tu as réservée ({c['nom']}) est prête depuis le {date_fr(c['date_disponibilite'])}."
        messages.append((c["email"], c["telephone"], f"Ta réservation de {c['nom']} est prête",
                         f"Bonjour {c['nom_client']}, {texte} Retrouve-la dans « Mes commandes » sur App Agricole."))

    # 2. Commandes en attente depuis plus de 48 h : relancer l'agriculteur
    limite = (datetime.now() - timedelta(hours=DELAI_RELANCE_HEURES)).strftime("%Y-%m-%d %H:%M:%S")
    for c in connexion_bd.execute(
        """SELECT commandes.id, recoltes.nom, utilisateurs.nom AS nom_agriculteur, utilisateurs.email,
                  utilisateurs.telephone
           FROM commandes JOIN recoltes ON commandes.recolte_id = recoltes.id
           JOIN utilisateurs ON recoltes.agriculteur_id = utilisateurs.id
           WHERE commandes.statut = 'en_attente' AND commandes.relance_envoyee = 0
             AND SUBSTR(commandes.date_creation, 1, 19) < ?""",
        (limite,)
    ).fetchall():
        connexion_bd.execute("UPDATE commandes SET relance_envoyee = 1 WHERE id = ?", (c["id"],))
        messages.append((c["email"], c["telephone"], f"Une commande de {c['nom']} attend ta réponse",
                         f"Bonjour {c['nom_agriculteur']}, une commande de {c['nom']} attend ta réponse depuis "
                         f"plus de 2 jours. Confirme-la ou refuse-la dans « Commandes reçues » sur App Agricole."))

    # 3. Premium qui se termine dans 3 jours
    fin = (date.today() + timedelta(days=JOURS_AVANT_FIN_PREMIUM)).isoformat()
    for u in connexion_bd.execute(
        """SELECT id, nom, email, telephone, premium_jusqu_au FROM utilisateurs
           WHERE premium_jusqu_au = ? AND (rappel_premium_pour IS NULL OR rappel_premium_pour <> premium_jusqu_au)
             AND suspendu = 0""",
        (fin,)
    ).fetchall():
        connexion_bd.execute("UPDATE utilisateurs SET rappel_premium_pour = premium_jusqu_au WHERE id = ?", (u["id"],))
        messages.append((u["email"], u["telephone"], "Ton abonnement Premium se termine bientôt",
                         f"Bonjour {u['nom']}, ton abonnement Premium se termine le {date_fr(u['premium_jusqu_au'])}. "
                         f"Renouvelle-le dans « Premium » sur App Agricole pour garder tes avantages."))

    connexion_bd.commit()
    return messages


@app.route("/taches/quotidiennes", methods=["POST"])
@csrf.exempt  # appelée par GitHub Actions, protégée par le jeton secret
def taches_quotidiennes():
    if not jeton_valide():
        abort(404)
    connexion_bd = get_connexion()
    from routes.commandes_regulieres import passer_commandes_du_jour  # import local : évite un cycle
    from routes.rapport_mensuel import preparer_rapports
    from routes.achats_groupes import expirer_groupes
    messages = preparer_rappels(connexion_bd) + passer_commandes_du_jour(connexion_bd) + expirer_groupes(connexion_bd)
    rapports = preparer_rapports(connexion_bd)
    connexion_bd.close()
    lien = url_for("accueil", _external=True)

    def envoyer():
        for email, telephone, sujet, texte in messages:
            envoyer_email(email, sujet, f"<p>{escape(texte)}</p><p><a href=\"{lien}\">{lien}</a></p>")
            sms.alerter(telephone, f"App Agricole : {texte}")
        for email, sujet, html in rapports:
            envoyer_email(email, sujet, html)

    # Envoi en arrière-plan : la réponse part tout de suite, même s'il y a beaucoup de rappels
    threading.Thread(target=envoyer, daemon=True).start()
    return jsonify({"rappels": len(messages), "rapports": len(rapports)})
