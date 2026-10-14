"""Négociation du prix d'une commande : le client propose un prix, l'agriculteur accepte,
refuse ou fait une contre-offre ; le client accepte la contre-offre ou propose à nouveau.
Tant qu'une offre attend une réponse, l'agriculteur ne peut pas confirmer la commande."""
from flask import abort, flash, redirect, request, session, url_for

import push
from database import get_connexion
from core import app, prix_valide, utilisateur_connecte

EN_COURS = ("proposee", "contre_offre")


def commande_negociable(connexion_bd, commande_id):
    return connexion_bd.execute(
        """SELECT commandes.*, recoltes.nom AS nom_recolte, recoltes.agriculteur_id,
                  clients.telephone AS telephone_client, agriculteurs.telephone AS telephone_agriculteur
           FROM commandes JOIN recoltes ON commandes.recolte_id = recoltes.id
           JOIN utilisateurs clients ON commandes.client_id = clients.id
           JOIN utilisateurs agriculteurs ON recoltes.agriculteur_id = agriculteurs.id
           WHERE commandes.id = ? AND commandes.statut = 'en_attente'""", (commande_id,)
    ).fetchone()


@app.route("/commandes/<int:commande_id>/offre", methods=["POST"])
def repondre_offre(commande_id):
    if not utilisateur_connecte():
        return redirect(url_for("connexion"))
    action = request.form.get("action", "")
    utilisateur_id = session["utilisateur_id"]
    connexion_bd = get_connexion()
    commande = commande_negociable(connexion_bd, commande_id)
    if commande is None or utilisateur_id not in (commande["client_id"], commande["agriculteur_id"]):
        connexion_bd.close()
        abort(404)
    est_agriculteur = utilisateur_id == commande["agriculteur_id"]
    retour = url_for("commandes_recues") if est_agriculteur else url_for("mes_commandes")

    try:
        prix = prix_valide(request.form.get("prix", "")) if action in ("contre_offre", "nouvelle_offre") else None
    except ValueError as erreur:
        connexion_bd.close()
        flash(str(erreur))
        return redirect(retour)

    # (qui peut, état attendu) -> (requête, message pour l'autre partie, message affiché)
    if est_agriculteur and action == "accepter" and commande["negociation"] == "proposee":
        connexion_bd.execute("UPDATE commandes SET negociation = 'acceptee', lu_client = 0 WHERE id = ?", (commande_id,))
        alerte = f"ton prix de {commande['prix_propose']} pour {commande['nom_recolte']} est accepté."
        flash("Offre acceptée. Tu peux maintenant confirmer la commande.")
    elif est_agriculteur and action == "contre_offre" and commande["negociation"] in EN_COURS:
        connexion_bd.execute("UPDATE commandes SET negociation = 'contre_offre', contre_offre = ?, lu_client = 0 WHERE id = ?",
                             (prix, commande_id))
        alerte = f"contre-offre pour {commande['nom_recolte']} : {prix}."
        flash("Contre-offre envoyée au client.")
    elif not est_agriculteur and action == "accepter" and commande["negociation"] == "contre_offre":
        connexion_bd.execute("UPDATE commandes SET negociation = 'acceptee', prix_propose = contre_offre, lu = 0 WHERE id = ?",
                             (commande_id,))
        alerte = f"le client accepte ton prix de {commande['contre_offre']} pour {commande['nom_recolte']}."
        flash("Prix accepté. L'agriculteur va confirmer ta commande.")
    elif not est_agriculteur and action == "nouvelle_offre" and commande["negociation"] in EN_COURS:
        connexion_bd.execute("UPDATE commandes SET negociation = 'proposee', prix_propose = ?, contre_offre = NULL, lu = 0 "
                             "WHERE id = ?", (prix, commande_id))
        alerte = f"nouvelle offre pour {commande['nom_recolte']} : {prix}."
        flash("Nouvelle offre envoyée.")
    else:
        connexion_bd.close()
        flash("Cette offre n'attend plus de réponse.")
        return redirect(retour)
    connexion_bd.commit()
    connexion_bd.close()

    if est_agriculteur:
        push.alerter(commande["client_id"], commande["telephone_client"], f"App Agricole : {alerte}", url_for("mes_commandes"))
    else:
        push.alerter(commande["agriculteur_id"], commande["telephone_agriculteur"], f"App Agricole : {alerte}",
                     url_for("commandes_recues"))
    return redirect(retour)
