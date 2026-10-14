"""Avis et notes : le client note l'agriculteur après une commande livrée."""
from flask import render_template, request, redirect, url_for, session, flash
from database import get_connexion
from core import app, utilisateur_connecte

LONGUEUR_MAX_COMMENTAIRE = 500

# Note moyenne et nombre d'avis par agriculteur, à joindre aux requêtes (LEFT JOIN ... ON agriculteur_id)
NOTES_AGRICULTEURS = """(SELECT agriculteur_id, AVG(note) AS note_moyenne, COUNT(*) AS nb_avis
                         FROM avis GROUP BY agriculteur_id)"""


@app.route("/mes-commandes/<int:commande_id>/avis", methods=["POST"])
def donner_avis(commande_id):
    if not utilisateur_connecte() or session["role"] != "client":
        return redirect(url_for("connexion"))

    try:
        note = int(request.form.get("note", ""))
    except ValueError:
        note = 0
    commentaire = request.form.get("commentaire", "").strip()
    if not 1 <= note <= 5:
        flash("Choisis une note entre 1 et 5 étoiles.")
        return redirect(url_for("mes_commandes"))
    if len(commentaire) > LONGUEUR_MAX_COMMENTAIRE:
        flash(f"Le commentaire ne doit pas dépasser {LONGUEUR_MAX_COMMENTAIRE} caractères.")
        return redirect(url_for("mes_commandes"))

    connexion_bd = get_connexion()
    # Seulement ses propres commandes livrées, et une seule fois
    commande = connexion_bd.execute(
        """SELECT recoltes.agriculteur_id FROM commandes
           JOIN recoltes ON commandes.recolte_id = recoltes.id
           WHERE commandes.id = ? AND commandes.client_id = ? AND commandes.statut = 'livree'
             AND NOT EXISTS (SELECT 1 FROM avis WHERE avis.commande_id = commandes.id)""",
        (commande_id, session["utilisateur_id"])
    ).fetchone()
    if commande:
        connexion_bd.execute(
            "INSERT INTO avis (commande_id, client_id, agriculteur_id, note, commentaire) VALUES (?, ?, ?, ?, ?)",
            (commande_id, session["utilisateur_id"], commande["agriculteur_id"], note, commentaire or None)
        )
        connexion_bd.commit()
        flash("Merci pour ton avis !")
    else:
        flash("Tu ne peux pas donner d'avis sur cette commande.")
    connexion_bd.close()
    return redirect(url_for("mes_commandes"))


@app.route("/agriculteurs/<int:agriculteur_id>/avis")
def avis_agriculteur(agriculteur_id):
    if not utilisateur_connecte():
        return redirect(url_for("connexion"))

    connexion_bd = get_connexion()
    agriculteur = connexion_bd.execute(
        f"""SELECT utilisateurs.id, utilisateurs.nom, utilisateurs.verification, notes.note_moyenne, notes.nb_avis
            FROM utilisateurs LEFT JOIN {NOTES_AGRICULTEURS} notes ON notes.agriculteur_id = utilisateurs.id
            WHERE utilisateurs.id = ? AND utilisateurs.role = 'agriculteur'""",
        (agriculteur_id,)
    ).fetchone()
    if agriculteur is None:
        connexion_bd.close()
        flash("Agriculteur introuvable.")
        return redirect(url_for("tableau_de_bord"))
    avis = connexion_bd.execute(
        """SELECT avis.note, avis.commentaire, avis.date_creation,
                  utilisateurs.nom AS nom_client, recoltes.nom AS nom_recolte
           FROM avis
           JOIN utilisateurs ON avis.client_id = utilisateurs.id
           JOIN commandes ON avis.commande_id = commandes.id
           JOIN recoltes ON commandes.recolte_id = recoltes.id
           WHERE avis.agriculteur_id = ?
           ORDER BY avis.date_creation DESC, avis.id DESC""",
        (agriculteur_id,)
    ).fetchall()
    connexion_bd.close()
    return render_template("avis_agriculteur.html", agriculteur=agriculteur, avis=avis)
