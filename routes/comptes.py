"""Accueil, inscription, connexion et profil."""
from flask import render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from database import get_connexion
from core import app, utilisateur_connecte


@app.route("/")
def accueil():
    return render_template("accueil.html")


@app.route("/inscription", methods=["GET", "POST"])
def inscription():
    if request.method == "POST":
        nom = request.form["nom"]
        email = request.form["email"]
        mot_de_passe = request.form["mot_de_passe"]
        role = request.form["role"]

        mot_de_passe_hache = generate_password_hash(mot_de_passe)

        connexion = get_connexion()
        try:
            connexion.execute(
                "INSERT INTO utilisateurs (nom, email, mot_de_passe, role) VALUES (?, ?, ?, ?)",
                (nom, email, mot_de_passe_hache, role)
            )
            connexion.commit()
        except Exception:
            flash("Cet email est déjà utilisé.")
            return redirect(url_for("inscription"))
        finally:
            connexion.close()

        flash("Compte créé avec succès, tu peux te connecter.")
        return redirect(url_for("connexion"))

    return render_template("inscription.html")


@app.route("/connexion", methods=["GET", "POST"])
def connexion():
    if request.method == "POST":
        email = request.form["email"]
        mot_de_passe = request.form["mot_de_passe"]

        connexion_bd = get_connexion()
        utilisateur = connexion_bd.execute(
            "SELECT * FROM utilisateurs WHERE email = ?", (email,)
        ).fetchone()
        connexion_bd.close()

        if utilisateur and check_password_hash(utilisateur["mot_de_passe"], mot_de_passe):
            session["utilisateur_id"] = utilisateur["id"]
            session["nom"] = utilisateur["nom"]
            session["role"] = utilisateur["role"]

            if utilisateur["role"] == "client":
                return redirect(url_for("espace_client"))
            elif utilisateur["role"] == "agriculteur":
                return redirect(url_for("espace_agriculteur"))
            elif utilisateur["role"] == "fournisseur":
                return redirect(url_for("espace_fournisseur"))
            elif utilisateur["role"] == "financeur":
                return redirect(url_for("espace_financeur"))
        else:
            flash("Email ou mot de passe incorrect.")
            return redirect(url_for("connexion"))

    return render_template("connexion.html")


@app.route("/deconnexion")
def deconnexion():
    session.clear()
    return redirect(url_for("accueil"))


@app.route("/mon-profil", methods=["GET", "POST"])
def mon_profil():
    if not utilisateur_connecte():
        return redirect(url_for("connexion"))

    connexion_bd = get_connexion()
    utilisateur = connexion_bd.execute(
        "SELECT * FROM utilisateurs WHERE id = ?", (session["utilisateur_id"],)
    ).fetchone()

    if request.method == "POST":
        nom = request.form["nom"]
        email = request.form["email"]
        mot_de_passe_actuel = request.form.get("mot_de_passe_actuel", "")
        nouveau_mot_de_passe = request.form.get("nouveau_mot_de_passe", "").strip()

        # Le mot de passe actuel est toujours requis pour confirmer un changement
        if not check_password_hash(utilisateur["mot_de_passe"], mot_de_passe_actuel):
            connexion_bd.close()
            flash("Mot de passe actuel incorrect.")
            return redirect(url_for("mon_profil"))

        if nouveau_mot_de_passe:
            mot_de_passe_a_enregistrer = generate_password_hash(nouveau_mot_de_passe)
        else:
            mot_de_passe_a_enregistrer = utilisateur["mot_de_passe"]

        try:
            connexion_bd.execute(
                "UPDATE utilisateurs SET nom = ?, email = ?, mot_de_passe = ? WHERE id = ?",
                (nom, email, mot_de_passe_a_enregistrer, session["utilisateur_id"])
            )
            connexion_bd.commit()
        except Exception:
            connexion_bd.rollback()
            connexion_bd.close()
            flash("Cet email est déjà utilisé par un autre compte.")
            return redirect(url_for("mon_profil"))

        connexion_bd.close()
        session["nom"] = nom
        flash("Profil mis à jour avec succès.")
        return redirect(url_for("mon_profil"))

    connexion_bd.close()
    return render_template("mon_profil.html", utilisateur=utilisateur)
