"""Reçu d'une commande livrée, pour le client et l'agriculteur (et l'admin) : page imprimable,
à enregistrer en PDF depuis le navigateur (« Imprimer » → « Enregistrer au format PDF »)."""
from flask import abort, redirect, render_template, session, url_for
from database import get_connexion
from core import app, est_admin, utilisateur_connecte


def numero_recu(commande):
    return f"REC-{commande['id']:06d}"


@app.route("/commande/<int:commande_id>/recu")
def recu_commande(commande_id):
    if not utilisateur_connecte():
        return redirect(url_for("connexion"))

    connexion_bd = get_connexion()
    commande = connexion_bd.execute(
        """SELECT commandes.*, recoltes.nom AS nom_recolte, recoltes.prix, recoltes.localite,
                  recoltes.agriculteur_id,
                  agriculteurs.nom AS nom_agriculteur, clients.nom AS nom_client
           FROM commandes
           JOIN recoltes ON commandes.recolte_id = recoltes.id
           JOIN utilisateurs agriculteurs ON recoltes.agriculteur_id = agriculteurs.id
           JOIN utilisateurs clients ON commandes.client_id = clients.id
           WHERE commandes.id = ? AND commandes.statut = 'livree'""", (commande_id,)
    ).fetchone()
    connexion_bd.close()

    utilisateur_id = session["utilisateur_id"]
    if commande is None or utilisateur_id not in (commande["client_id"], commande["agriculteur_id"]) \
            and not est_admin():
        abort(404)

    frais = commande["frais_livraison"] or 0
    montant = commande["montant"] or 0
    return render_template(
        "recu.html", commande=commande, numero=numero_recu(commande),
        frais=frais, montant=montant, total=commande["montant_a_payer"] or montant + frais,
        # La commission ne regarde que l'agriculteur (et l'admin), pas le client
        voir_commission=utilisateur_id != commande["client_id"],
    )
