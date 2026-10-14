"""Fiabilité des clients : l'agriculteur note le client après une commande livrée ou annulée.

Les autres agriculteurs voient la note moyenne et le nombre de commandes livrées du client avant
de confirmer une commande (utile contre les clients qui ne viennent pas chercher leur commande).
Pas de commentaire : seulement une note, pour rester factuel."""
from flask import request, redirect, url_for, session, flash

from database import get_connexion
from core import app, utilisateur_connecte

# Note moyenne reçue par chaque client et nombre de ses commandes livrées, à joindre (LEFT JOIN ... ON client_id)
FIABILITE_CLIENTS = """(SELECT client_id, AVG(note) AS note_client, COUNT(*) AS nb_notes_client
                        FROM avis_clients GROUP BY client_id)"""
LIVRAISONS_CLIENTS = """(SELECT client_id, COUNT(*) AS nb_livrees_client
                         FROM commandes WHERE statut = 'livree' GROUP BY client_id)"""


def fiabilite_du_client(connexion_bd, client_id):
    """{note_client, nb_notes_client} du client (note None s'il n'a encore jamais été noté)."""
    return connexion_bd.execute(
        "SELECT AVG(note) AS note_client, COUNT(*) AS nb_notes_client FROM avis_clients WHERE client_id = ?",
        (client_id,)).fetchone()


@app.route("/espace-agriculteur/commandes/<int:commande_id>/noter-client", methods=["POST"])
def noter_client(commande_id):
    if not utilisateur_connecte() or session["role"] != "agriculteur":
        return redirect(url_for("connexion"))
    note = request.form.get("note", type=int)
    if note is None or not 1 <= note <= 5:
        flash("Choisis une note entre 1 et 5 étoiles.")
        return redirect(url_for("commandes_recues"))

    connexion_bd = get_connexion()
    # Seulement une commande terminée reçue par cet agriculteur, et une seule note
    commande = connexion_bd.execute(
        """SELECT commandes.client_id FROM commandes
           JOIN recoltes ON commandes.recolte_id = recoltes.id
           WHERE commandes.id = ? AND recoltes.agriculteur_id = ? AND commandes.statut IN ('livree', 'annulee')
             AND NOT EXISTS (SELECT 1 FROM avis_clients WHERE avis_clients.commande_id = commandes.id)""",
        (commande_id, session["utilisateur_id"])
    ).fetchone()
    if commande:
        connexion_bd.execute(
            "INSERT INTO avis_clients (commande_id, agriculteur_id, client_id, note) VALUES (?, ?, ?, ?)",
            (commande_id, session["utilisateur_id"], commande["client_id"], note))
        connexion_bd.commit()
        flash("Merci : ta note aide les autres agriculteurs.")
    else:
        flash("Tu ne peux pas noter ce client pour cette commande.")
    connexion_bd.close()
    return redirect(url_for("commandes_recues"))
