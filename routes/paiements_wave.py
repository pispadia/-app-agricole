"""Paiement en ligne par Wave : abonnement Premium, commissions des agriculteurs et
commandes payées par les clients (la plateforme garde sa commission et reverse le reste)."""
from flask import redirect, request, url_for, session, flash
from database import get_connexion
from core import app, utilisateur_connecte, PRIX_PREMIUM_MENSUEL
import sms
import wave
from routes.premium import prolonger_premium


def commissions_dues(connexion_bd, agriculteur_id):
    return connexion_bd.execute(
        """SELECT commandes.id, commandes.commission FROM commandes
           JOIN recoltes ON commandes.recolte_id = recoltes.id
           WHERE recoltes.agriculteur_id = ? AND commandes.statut = 'livree'
             AND commandes.commission_payee = 0 AND commandes.commission > 0""",
        (agriculteur_id,)
    ).fetchall()


def demarrer_paiement(objet, montant, details=None):
    """Enregistre le paiement, crée la session Wave et envoie l'utilisateur payer dans Wave."""
    connexion_bd = get_connexion()
    paiement_id = connexion_bd.execute(
        "INSERT INTO paiements_wave (utilisateur_id, objet, montant, details) VALUES (?, ?, ?, ?) RETURNING id",
        (session["utilisateur_id"], objet, montant, details)
    ).fetchone()["id"]
    connexion_bd.commit()
    try:
        id_session, lien = wave.creer_session(
            montant, f"paiement-{paiement_id}",
            url_for("retour_paiement_wave", paiement_id=paiement_id, _external=True),
            url_for("erreur_paiement_wave", paiement_id=paiement_id, _external=True),
        )
    except Exception as erreur:
        print(f"[wave] Création de session impossible : {erreur}")
        connexion_bd.execute("UPDATE paiements_wave SET statut = 'echec' WHERE id = ?", (paiement_id,))
        connexion_bd.commit()
        connexion_bd.close()
        flash("Le paiement Wave est momentanément indisponible. Réessaie plus tard.")
        return None
    connexion_bd.execute("UPDATE paiements_wave SET session_id = ? WHERE id = ?", (id_session, paiement_id))
    connexion_bd.commit()
    connexion_bd.close()
    return redirect(lien)


def verifier_paiement(connexion_bd, paiement):
    """Interroge Wave ; si la session est payée, applique le paiement une seule fois. Retourne True si payé."""
    if paiement["statut"] == "paye":
        return True
    if paiement["statut"] != "en_attente" or not paiement["session_id"]:
        return False
    try:
        if not wave.session_payee(paiement["session_id"], paiement["montant"]):
            return False
    except Exception as erreur:
        print(f"[wave] Vérification impossible pour le paiement {paiement['id']} : {erreur}")
        return False

    # Le passage en_attente -> paye ne réussit qu'une fois, même si deux requêtes arrivent ensemble
    resultat = connexion_bd.execute(
        "UPDATE paiements_wave SET statut = 'paye' WHERE id = ? AND statut = 'en_attente'", (paiement["id"],)
    )
    if resultat.rowcount:
        if paiement["objet"] == "premium":
            prolonger_premium(connexion_bd, paiement["utilisateur_id"])
            # Visible dans les revenus de l'espace admin, comme un paiement manuel validé
            connexion_bd.execute(
                "INSERT INTO paiements_premium (utilisateur_id, reference, montant, statut) VALUES (?, ?, ?, 'valide')",
                (paiement["utilisateur_id"], f"Wave {paiement['session_id']}", paiement["montant"])
            )
        elif paiement["objet"] == "commande":
            commande_id = int(paiement["details"])
            # La commission est retenue sur le paiement : elle est donc réglée d'office
            connexion_bd.execute(
                "UPDATE commandes SET paye_en_ligne = 1, commission_payee = 1, lu = 0 WHERE id = ?", (commande_id,)
            )
            agriculteur = connexion_bd.execute(
                """SELECT utilisateurs.telephone, recoltes.nom FROM commandes
                   JOIN recoltes ON commandes.recolte_id = recoltes.id
                   JOIN utilisateurs ON recoltes.agriculteur_id = utilisateurs.id
                   WHERE commandes.id = ?""", (commande_id,)
            ).fetchone()
            sms.alerter(agriculteur["telephone"],
                        f"App Agricole : la commande de {agriculteur['nom']} est payée en ligne. Tu peux livrer.")
        else:
            for commande_id in (paiement["details"] or "").split(","):
                if commande_id:
                    connexion_bd.execute("UPDATE commandes SET commission_payee = 1 WHERE id = ?",
                                         (int(commande_id),))
    connexion_bd.commit()
    return True


def verifier_paiements_en_attente(utilisateur_id):
    """Rattrape les paiements dont l'utilisateur n'est pas revenu sur le site après avoir payé."""
    connexion_bd = get_connexion()
    for paiement in connexion_bd.execute(
        "SELECT * FROM paiements_wave WHERE utilisateur_id = ? AND statut = 'en_attente' AND session_id IS NOT NULL",
        (utilisateur_id,)
    ).fetchall():
        verifier_paiement(connexion_bd, paiement)
    connexion_bd.close()


@app.context_processor
def injecter_wave():
    return {"wave_actif": wave.wave_active()}


@app.before_request
def rattraper_paiements_wave():
    """Sur les pages qui affichent un abonnement ou des commissions, confirme les paiements restés en attente."""
    if (wave.wave_active() and utilisateur_connecte()
            and request.endpoint in ("premium", "commandes_recues", "mes_commandes")):
        verifier_paiements_en_attente(session["utilisateur_id"])


@app.route("/paiement/wave/premium", methods=["POST"])
def payer_premium_wave():
    if not utilisateur_connecte():
        return redirect(url_for("connexion"))
    if not wave.wave_active():
        return redirect(url_for("premium"))
    return demarrer_paiement("premium", PRIX_PREMIUM_MENSUEL) or redirect(url_for("premium"))


@app.route("/paiement/wave/commissions", methods=["POST"])
def payer_commissions_wave():
    if not utilisateur_connecte() or session["role"] != "agriculteur":
        return redirect(url_for("connexion"))
    if not wave.wave_active():
        return redirect(url_for("commandes_recues"))
    connexion_bd = get_connexion()
    dues = commissions_dues(connexion_bd, session["utilisateur_id"])
    connexion_bd.close()
    if not dues:
        flash("Aucune commission à régler.")
        return redirect(url_for("commandes_recues"))
    montant = sum(c["commission"] for c in dues)
    details = ",".join(str(c["id"]) for c in dues)
    return demarrer_paiement("commission", montant, details) or redirect(url_for("commandes_recues"))


@app.route("/paiement/wave/commande/<int:commande_id>", methods=["POST"])
def payer_commande_wave(commande_id):
    if not utilisateur_connecte() or session["role"] != "client":
        return redirect(url_for("connexion"))
    if not wave.wave_active():
        return redirect(url_for("mes_commandes"))
    connexion_bd = get_connexion()
    commande = connexion_bd.execute(
        """SELECT montant_a_payer FROM commandes
           WHERE id = ? AND client_id = ? AND statut = 'confirmee' AND mode_paiement = 'wave'
             AND paye_en_ligne = 0 AND montant_a_payer > 0""",
        (commande_id, session["utilisateur_id"])
    ).fetchone()
    connexion_bd.close()
    if commande is None:
        flash("Cette commande ne peut pas être payée en ligne.")
        return redirect(url_for("mes_commandes"))
    return (demarrer_paiement("commande", commande["montant_a_payer"], str(commande_id))
            or redirect(url_for("mes_commandes")))


PAGES_APRES_PAIEMENT = {"premium": "premium", "commission": "commandes_recues", "commande": "mes_commandes"}
MESSAGES_PAIEMENT_RECU = {
    "premium": "Ton abonnement Premium est actif.",
    "commission": "Tes commissions sont réglées.",
    "commande": "Ta commande est payée, l'agriculteur est prévenu.",
}


def paiement_de_l_utilisateur(connexion_bd, paiement_id):
    return connexion_bd.execute(
        "SELECT * FROM paiements_wave WHERE id = ? AND utilisateur_id = ?",
        (paiement_id, session["utilisateur_id"])
    ).fetchone()


@app.route("/paiement/wave/retour/<int:paiement_id>")
def retour_paiement_wave(paiement_id):
    if not utilisateur_connecte():
        return redirect(url_for("connexion"))
    connexion_bd = get_connexion()
    paiement = paiement_de_l_utilisateur(connexion_bd, paiement_id)
    if paiement is None:
        connexion_bd.close()
        return redirect(url_for("accueil"))

    if verifier_paiement(connexion_bd, paiement):
        flash("Paiement Wave reçu, merci ! " + MESSAGES_PAIEMENT_RECU[paiement["objet"]])
    else:
        flash("Ton paiement n'est pas encore confirmé par Wave. Il sera pris en compte dès sa confirmation.")
    connexion_bd.close()
    return redirect(url_for(PAGES_APRES_PAIEMENT[paiement["objet"]]))


@app.route("/paiement/wave/erreur/<int:paiement_id>")
def erreur_paiement_wave(paiement_id):
    if not utilisateur_connecte():
        return redirect(url_for("connexion"))
    connexion_bd = get_connexion()
    paiement = paiement_de_l_utilisateur(connexion_bd, paiement_id)
    # On demande d'abord à Wave : ce lien peut être ouvert par erreur (ou par un lien piégé)
    # alors que le paiement a bien eu lieu ; il ne doit jamais faire perdre un paiement.
    if paiement and verifier_paiement(connexion_bd, paiement):
        connexion_bd.close()
        flash("Paiement Wave reçu, merci ! " + MESSAGES_PAIEMENT_RECU[paiement["objet"]])
        return redirect(url_for(PAGES_APRES_PAIEMENT[paiement["objet"]]))
    if paiement and paiement["statut"] == "en_attente":
        connexion_bd.execute("UPDATE paiements_wave SET statut = 'echec' WHERE id = ?", (paiement_id,))
        connexion_bd.commit()
    connexion_bd.close()
    flash("Le paiement Wave n'a pas abouti. Tu peux réessayer.")
    return redirect(url_for(PAGES_APRES_PAIEMENT[paiement["objet"]] if paiement else "accueil"))
