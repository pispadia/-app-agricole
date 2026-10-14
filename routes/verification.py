"""Badge « Agriculteur vérifié » : l'agriculteur envoie une photo de sa pièce d'identité,
l'admin la compare au nom du compte et valide ou refuse. La pièce est effacée dès la décision."""
import base64

from flask import abort, flash, redirect, render_template, request, Response, session, url_for
from database import get_connexion
from core import app, encoder_photo, utilisateur_connecte
from routes.premium import admin_requis
import sms


@app.route("/espace-agriculteur/verification", methods=["GET", "POST"])
def demande_verification():
    if not utilisateur_connecte() or session["role"] != "agriculteur":
        return redirect(url_for("connexion"))

    utilisateur_id = session["utilisateur_id"]
    connexion_bd = get_connexion()
    statut = connexion_bd.execute(
        "SELECT verification FROM utilisateurs WHERE id = ?", (utilisateur_id,)).fetchone()["verification"]

    if request.method == "POST" and statut not in ("verifie", "en_attente"):
        piece = encoder_photo(request.files.get("piece"))
        if piece:
            connexion_bd.execute("DELETE FROM verifications WHERE utilisateur_id = ?", (utilisateur_id,))
            connexion_bd.execute("INSERT INTO verifications (utilisateur_id, piece) VALUES (?, ?)",
                                 (utilisateur_id, piece))
            connexion_bd.execute("UPDATE utilisateurs SET verification = 'en_attente' WHERE id = ?",
                                 (utilisateur_id,))
            connexion_bd.commit()
            flash("Pièce envoyée : nous la vérifions et te prévenons par SMS.")
            connexion_bd.close()
            return redirect(url_for("demande_verification"))
        flash("Envoie une photo lisible de ta pièce d'identité (JPG, PNG ou WEBP, 2 Mo maximum).")

    connexion_bd.close()
    return render_template("verification.html", statut=statut)


@app.route("/admin/verifications")
@admin_requis
def admin_verifications():
    connexion_bd = get_connexion()
    demandes = connexion_bd.execute(
        """SELECT verifications.utilisateur_id, verifications.date_creation,
                  utilisateurs.nom, utilisateurs.email, utilisateurs.telephone
           FROM verifications JOIN utilisateurs ON verifications.utilisateur_id = utilisateurs.id
           WHERE utilisateurs.verification = 'en_attente'
           ORDER BY verifications.date_creation"""
    ).fetchall()
    connexion_bd.close()
    return render_template("admin_verifications.html", demandes=demandes)


@app.route("/admin/verifications/<int:utilisateur_id>/piece")
@admin_requis
def piece_identite(utilisateur_id):
    connexion_bd = get_connexion()
    ligne = connexion_bd.execute(
        "SELECT piece FROM verifications WHERE utilisateur_id = ?", (utilisateur_id,)).fetchone()
    connexion_bd.close()
    if ligne is None or ";base64," not in ligne["piece"]:
        abort(404)
    entete, donnees = ligne["piece"].split(",", 1)
    reponse = Response(base64.b64decode(donnees), mimetype=entete[len("data:"):].split(";")[0])
    reponse.headers["Cache-Control"] = "no-store"  # document d'identité : jamais gardé en cache
    return reponse


@app.route("/admin/verifications/<int:utilisateur_id>/<decision>", methods=["POST"])
@admin_requis
def decider_verification(utilisateur_id, decision):
    if decision not in ("valider", "refuser"):
        abort(404)
    connexion_bd = get_connexion()
    utilisateur = connexion_bd.execute(
        "SELECT telephone FROM utilisateurs WHERE id = ? AND verification = 'en_attente'",
        (utilisateur_id,)).fetchone()
    if utilisateur:
        valide = decision == "valider"
        connexion_bd.execute("UPDATE utilisateurs SET verification = ? WHERE id = ?",
                             ("verifie" if valide else "refuse", utilisateur_id))
        connexion_bd.execute("DELETE FROM verifications WHERE utilisateur_id = ?", (utilisateur_id,))
        connexion_bd.commit()
        sms.alerter(utilisateur["telephone"],
                    "App Agricole : ton compte est vérifié, le badge apparaît sur tes annonces." if valide else
                    "App Agricole : ta pièce d'identité n'a pas pu être vérifiée. Renvoie une photo lisible.")
        flash("Agriculteur vérifié." if valide else "Vérification refusée.")
    connexion_bd.close()
    return redirect(url_for("admin_verifications"))
