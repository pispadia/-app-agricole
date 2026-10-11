"""Accueil, inscription, connexion et profil."""
import time

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


# Après MAX_ECHECS mots de passe faux pour un même email en DUREE_BLOCAGE secondes,
# la connexion à ce compte est refusée jusqu'à ce que les plus anciens échecs expirent.
MAX_ECHECS = 5
DUREE_BLOCAGE = 15 * 60


def nombre_echecs_recents(connexion_bd, email):
    return connexion_bd.execute(
        "SELECT COUNT(*) AS n FROM echecs_connexion WHERE email = ? AND instant > ?",
        (email, int(time.time()) - DUREE_BLOCAGE)
    ).fetchone()["n"]


def enregistrer_echec(connexion_bd, email):
    maintenant = int(time.time())
    connexion_bd.execute("DELETE FROM echecs_connexion WHERE instant <= ?", (maintenant - DUREE_BLOCAGE,))
    connexion_bd.execute(
        "INSERT INTO echecs_connexion (email, instant) VALUES (?, ?)", (email, maintenant)
    )
    connexion_bd.commit()


@app.route("/connexion", methods=["GET", "POST"])
def connexion():
    if request.method == "POST":
        email = request.form["email"]
        mot_de_passe = request.form["mot_de_passe"]
        cle_echecs = email.strip().lower()

        connexion_bd = get_connexion()
        if nombre_echecs_recents(connexion_bd, cle_echecs) >= MAX_ECHECS:
            connexion_bd.close()
            flash("Trop de tentatives de connexion pour ce compte. Réessayez dans 15 minutes.")
            return redirect(url_for("connexion"))

        utilisateur = connexion_bd.execute(
            "SELECT * FROM utilisateurs WHERE email = ?", (email,)
        ).fetchone()

        if not (utilisateur and check_password_hash(utilisateur["mot_de_passe"], mot_de_passe)):
            enregistrer_echec(connexion_bd, cle_echecs)
            connexion_bd.close()
            flash("Email ou mot de passe incorrect.")
            return redirect(url_for("connexion"))

        connexion_bd.execute("DELETE FROM echecs_connexion WHERE email = ?", (cle_echecs,))
        connexion_bd.commit()
        connexion_bd.close()

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
