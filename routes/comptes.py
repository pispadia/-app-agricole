"""Accueil, inscription, connexion et profil."""
import time

from flask import render_template, request, redirect, url_for, session, flash
from itsdangerous import URLSafeTimedSerializer, BadSignature
from markupsafe import escape
from werkzeug.security import generate_password_hash, check_password_hash
from database import get_connexion
from emails import envoyer_email
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


# Lien de réinitialisation du mot de passe : signé avec la clé secrète, valable une
# heure, et lié au mot de passe actuel (il ne sert plus une fois le mot de passe changé).
DUREE_LIEN_REINITIALISATION = 60 * 60


def serialiseur_reinitialisation():
    return URLSafeTimedSerializer(app.secret_key, salt="reinitialisation-mot-de-passe")


def creer_jeton_reinitialisation(utilisateur):
    return serialiseur_reinitialisation().dumps(
        {"id": utilisateur["id"], "empreinte": utilisateur["mot_de_passe"][-16:]}
    )


def utilisateur_du_jeton(connexion_bd, jeton):
    """Retourne l'utilisateur visé par le lien, ou None si le lien est invalide ou expiré."""
    try:
        donnees = serialiseur_reinitialisation().loads(jeton, max_age=DUREE_LIEN_REINITIALISATION)
    except BadSignature:
        return None
    utilisateur = connexion_bd.execute(
        "SELECT * FROM utilisateurs WHERE id = ?", (donnees["id"],)
    ).fetchone()
    if utilisateur is None or utilisateur["mot_de_passe"][-16:] != donnees["empreinte"]:
        return None
    return utilisateur


@app.route("/mot-de-passe-oublie", methods=["GET", "POST"])
def mot_de_passe_oublie():
    if request.method == "POST":
        email = request.form["email"].strip()

        connexion_bd = get_connexion()
        utilisateur = connexion_bd.execute(
            "SELECT * FROM utilisateurs WHERE email = ?", (email,)
        ).fetchone()
        connexion_bd.close()

        if utilisateur:
            lien = url_for("reinitialiser_mot_de_passe",
                           jeton=creer_jeton_reinitialisation(utilisateur), _external=True)
            envoye = envoyer_email(
                utilisateur["email"],
                "Réinitialisation de votre mot de passe",
                f"<p>Bonjour {escape(utilisateur['nom'])},</p>"
                f"<p>Pour choisir un nouveau mot de passe, cliquez sur ce lien (valable 1 heure) :</p>"
                f'<p><a href="{lien}">{lien}</a></p>'
                f"<p>Si vous n'êtes pas à l'origine de cette demande, ignorez cet e-mail.</p>",
            )
            if not envoye:
                flash("L'e-mail n'a pas pu être envoyé. Réessayez plus tard.")
                return redirect(url_for("mot_de_passe_oublie"))

        # Même message que le compte existe ou non, pour ne pas révéler les emails inscrits
        flash("Si un compte existe avec cet email, un lien de réinitialisation vient d'y être envoyé.")
        return redirect(url_for("connexion"))

    return render_template("mot_de_passe_oublie.html")


@app.route("/reinitialiser-mot-de-passe/<jeton>", methods=["GET", "POST"])
def reinitialiser_mot_de_passe(jeton):
    connexion_bd = get_connexion()
    utilisateur = utilisateur_du_jeton(connexion_bd, jeton)
    if utilisateur is None:
        connexion_bd.close()
        flash("Ce lien est invalide ou a expiré. Faites une nouvelle demande.")
        return redirect(url_for("mot_de_passe_oublie"))

    if request.method == "POST":
        mot_de_passe = request.form["mot_de_passe"]
        if not mot_de_passe or mot_de_passe != request.form["confirmation"]:
            connexion_bd.close()
            flash("Les deux mots de passe doivent être identiques.")
            return redirect(url_for("reinitialiser_mot_de_passe", jeton=jeton))

        connexion_bd.execute(
            "UPDATE utilisateurs SET mot_de_passe = ? WHERE id = ?",
            (generate_password_hash(mot_de_passe), utilisateur["id"])
        )
        # Lève un éventuel blocage dû aux tentatives de connexion échouées
        connexion_bd.execute(
            "DELETE FROM echecs_connexion WHERE email = ?", (utilisateur["email"].strip().lower(),)
        )
        connexion_bd.commit()
        connexion_bd.close()
        flash("Mot de passe modifié, vous pouvez vous connecter.")
        return redirect(url_for("connexion"))

    connexion_bd.close()
    return render_template("reinitialiser_mot_de_passe.html")


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
