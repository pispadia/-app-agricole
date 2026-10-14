"""Messagerie d'une commande : le client et l'agriculteur échangent sur la plateforme,
sans voir leurs numéros ni leurs e-mails."""
from flask import render_template, request, redirect, url_for, session, flash
from database import get_connexion
from core import app, utilisateur_connecte, masquer_coordonnees

LONGUEUR_MAX_MESSAGE = 1000


def commande_de_la_conversation(connexion_bd, commande_id, utilisateur_id):
    """La commande si l'utilisateur en est le client ou l'agriculteur, sinon None."""
    return connexion_bd.execute(
        """SELECT commandes.id, commandes.client_id, commandes.statut, commandes.quantite_demandee,
                  recoltes.agriculteur_id, recoltes.nom AS nom_recolte,
                  clients.nom AS nom_client, agriculteurs.nom AS nom_agriculteur
           FROM commandes
           JOIN recoltes ON commandes.recolte_id = recoltes.id
           JOIN utilisateurs clients ON commandes.client_id = clients.id
           JOIN utilisateurs agriculteurs ON recoltes.agriculteur_id = agriculteurs.id
           WHERE commandes.id = ? AND (commandes.client_id = ? OR recoltes.agriculteur_id = ?)""",
        (commande_id, utilisateur_id, utilisateur_id)
    ).fetchone()


@app.route("/commandes/<int:commande_id>/messages", methods=["GET", "POST"])
def messages_commande(commande_id):
    if not utilisateur_connecte():
        return redirect(url_for("connexion"))

    utilisateur_id = session["utilisateur_id"]
    connexion_bd = get_connexion()
    commande = commande_de_la_conversation(connexion_bd, commande_id, utilisateur_id)
    if commande is None:
        connexion_bd.close()
        flash("Conversation introuvable.")
        return redirect(url_for("tableau_de_bord"))

    est_client = commande["client_id"] == utilisateur_id
    interlocuteur_id = commande["agriculteur_id"] if est_client else commande["client_id"]

    if request.method == "POST":
        contenu = request.form.get("contenu", "").strip()
        if not contenu:
            flash("Écris un message avant d'envoyer.")
        elif len(contenu) > LONGUEUR_MAX_MESSAGE:
            flash(f"Le message ne doit pas dépasser {LONGUEUR_MAX_MESSAGE} caractères.")
        else:
            connexion_bd.execute(
                """INSERT INTO messages_commande (commande_id, auteur_id, destinataire_id, contenu)
                   VALUES (?, ?, ?, ?)""",
                (commande_id, utilisateur_id, interlocuteur_id, masquer_coordonnees(contenu))
            )
            connexion_bd.commit()
        connexion_bd.close()
        return redirect(url_for("messages_commande", commande_id=commande_id))

    messages = connexion_bd.execute(
        "SELECT * FROM messages_commande WHERE commande_id = ? ORDER BY date_creation, id",
        (commande_id,)
    ).fetchall()
    # Les messages reçus affichés ici sont lus
    connexion_bd.execute(
        "UPDATE messages_commande SET lu = 1 WHERE commande_id = ? AND destinataire_id = ?",
        (commande_id, utilisateur_id)
    )
    connexion_bd.commit()
    connexion_bd.close()

    return render_template(
        "messagerie.html", commande=commande, messages=messages,
        interlocuteur=commande["nom_agriculteur"] if est_client else commande["nom_client"],
        retour=url_for("mes_commandes") if est_client else url_for("commandes_recues"),
    )
