"""Signalement des annonces et modération par l'admin.
Au SEUIL_MASQUAGE-ième signalement (personnes différentes), l'annonce est masquée en attendant
la décision de l'admin : masquer définitivement, rétablir, ou suspendre le vendeur."""
from flask import render_template, request, redirect, url_for, session, flash
from database import get_connexion
from core import app, utilisateur_connecte, masquer_coordonnees
from routes.premium import admin_requis

SEUIL_MASQUAGE = 3
MOTIFS = {
    "arnaque": "Arnaque ou vendeur suspect",
    "prix": "Prix ou quantité faux",
    "interdit": "Produit interdit ou contenu choquant",
    "contact": "Numéro ou contact pour contourner la plateforme",
    "autre": "Autre",
}


@app.route("/annonce/<int:recolte_id>/signaler", methods=["GET", "POST"])
def signaler_annonce(recolte_id):
    if not utilisateur_connecte():
        return redirect(url_for("connexion", suivant=url_for("signaler_annonce", recolte_id=recolte_id)))
    connexion_bd = get_connexion()
    recolte = connexion_bd.execute(
        "SELECT id, nom, agriculteur_id FROM recoltes WHERE id = ? AND masquee = 0", (recolte_id,)
    ).fetchone()
    if recolte is None or recolte["agriculteur_id"] == session["utilisateur_id"]:
        connexion_bd.close()
        return redirect(url_for("accueil"))

    if request.method == "POST":
        motif = request.form.get("motif", "")
        if motif not in MOTIFS:
            connexion_bd.close()
            flash("Choisis la raison du signalement.")
            return redirect(url_for("signaler_annonce", recolte_id=recolte_id))
        deja = connexion_bd.execute(
            "SELECT 1 FROM signalements WHERE recolte_id = ? AND auteur_id = ?", (recolte_id, session["utilisateur_id"])
        ).fetchone()
        if not deja:
            connexion_bd.execute(
                "INSERT INTO signalements (recolte_id, auteur_id, motif, commentaire) VALUES (?, ?, ?, ?)",
                (recolte_id, session["utilisateur_id"], motif,
                 masquer_coordonnees(request.form.get("commentaire", "").strip()[:500]) or None)
            )
            ouverts = connexion_bd.execute(
                "SELECT COUNT(*) AS n FROM signalements WHERE recolte_id = ? AND statut = 'ouvert'", (recolte_id,)
            ).fetchone()["n"]
            if ouverts >= SEUIL_MASQUAGE:
                connexion_bd.execute("UPDATE recoltes SET masquee = 1 WHERE id = ?", (recolte_id,))
            connexion_bd.commit()
        connexion_bd.close()
        flash("Merci, ton signalement a été transmis à l'équipe App Agricole.")
        return redirect(url_for("catalogue_public"))

    connexion_bd.close()
    return render_template("signaler.html", recolte=recolte, motifs=MOTIFS)


@app.route("/admin/signalements")
@admin_requis
def admin_signalements():
    connexion_bd = get_connexion()
    annonces = connexion_bd.execute(
        """SELECT recoltes.id, recoltes.nom, recoltes.masquee, recoltes.agriculteur_id,
                  utilisateurs.nom AS nom_agriculteur, utilisateurs.suspendu, COUNT(*) AS nombre
           FROM signalements
           JOIN recoltes ON signalements.recolte_id = recoltes.id
           JOIN utilisateurs ON recoltes.agriculteur_id = utilisateurs.id
           WHERE signalements.statut = 'ouvert'
           GROUP BY recoltes.id, recoltes.nom, recoltes.masquee, recoltes.agriculteur_id,
                    utilisateurs.nom, utilisateurs.suspendu
           ORDER BY COUNT(*) DESC"""
    ).fetchall()
    details = {}
    for ligne in connexion_bd.execute(
        """SELECT signalements.recolte_id, signalements.motif, signalements.commentaire, utilisateurs.nom
           FROM signalements JOIN utilisateurs ON signalements.auteur_id = utilisateurs.id
           WHERE signalements.statut = 'ouvert' ORDER BY signalements.id"""
    ).fetchall():
        details.setdefault(ligne["recolte_id"], []).append(ligne)
    connexion_bd.close()
    return render_template("admin_signalements.html", annonces=annonces, details=details, motifs=MOTIFS)


@app.route("/admin/signalements/<int:recolte_id>/<decision>", methods=["POST"])
@admin_requis
def decider_signalement(recolte_id, decision):
    """« masquer » : l'annonce reste cachée ; « retablir » : signalements rejetés, annonce visible."""
    if decision in ("masquer", "retablir"):
        connexion_bd = get_connexion()
        connexion_bd.execute("UPDATE recoltes SET masquee = ? WHERE id = ?",
                             (1 if decision == "masquer" else 0, recolte_id))
        connexion_bd.execute("UPDATE signalements SET statut = ? WHERE recolte_id = ? AND statut = 'ouvert'",
                             ("traite" if decision == "masquer" else "rejete", recolte_id))
        connexion_bd.commit()
        connexion_bd.close()
        flash("Annonce masquée." if decision == "masquer" else "Annonce rétablie, signalements rejetés.")
    return redirect(url_for("admin_signalements"))
