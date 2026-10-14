"""Accueil, inscription, connexion et profil."""
import time

from flask import render_template, request, redirect, url_for, session, flash
from itsdangerous import URLSafeTimedSerializer, BadSignature
from markupsafe import escape
from werkzeug.security import generate_password_hash, check_password_hash
from database import get_connexion
from emails import envoyer_email
from core import (app, utilisateur_connecte, mot_de_passe_valide, telephone_valide, ROLES,
                  utilisateur_courant, email_confirme, limite_atteinte)

# Limites anti-abus (chaque e-mail envoyé consomme le quota Brevo : 300 par jour en offre gratuite).
# Les inscriptions sont comptées par adresse IP ; une IP peut être partagée (réseau mobile,
# cybercafé), d'où une limite large.
MAX_INSCRIPTIONS_PAR_IP = 20
MAX_LIENS_PAR_EMAIL = 3
MAX_LIENS_PAR_IP = 10
UNE_HEURE = 3600


@app.route("/")
def accueil():
    # Déjà connecté : rien à faire sur la page d'inscription / connexion
    if utilisateur_connecte():
        return redirect(url_for("tableau_de_bord"))
    return render_template("accueil.html")


def memoriser_page_suivante():
    """Mémorise la page où aller après la connexion (ex: commander depuis une annonce partagée).
    Seulement un chemin de ce site, pour ne jamais rediriger vers un site extérieur."""
    suivant = request.args.get("suivant", "")
    if suivant.startswith("/") and not suivant.startswith(("//", "/\\")):
        session["suivant"] = suivant


@app.route("/inscription", methods=["GET", "POST"])
def inscription():
    memoriser_page_suivante()
    if request.args.get("parrain"):
        session["parrain"] = request.args["parrain"][:20]
    if request.method == "POST":
        nom = request.form["nom"]
        email = request.form["email"]
        mot_de_passe = request.form["mot_de_passe"]
        role = request.form.get("role", "")

        try:
            if role not in ROLES:
                raise ValueError("Choisis un type de compte dans la liste.")
            mot_de_passe_valide(mot_de_passe)
            telephone = telephone_valide(request.form.get("telephone", ""))
        except ValueError as erreur:
            flash(str(erreur))
            return render_template("inscription.html", saisie=request.form)

        if limite_atteinte(f"inscription-ip:{request.remote_addr}", MAX_INSCRIPTIONS_PAR_IP, UNE_HEURE):
            flash("Trop de comptes créés depuis cette connexion. Réessaie dans une heure.")
            return render_template("inscription.html", saisie=request.form)

        mot_de_passe_hache = generate_password_hash(mot_de_passe)

        connexion = get_connexion()
        try:
            connexion.execute(
                "INSERT INTO utilisateurs (nom, email, mot_de_passe, role, telephone) VALUES (?, ?, ?, ?, ?)",
                (nom, email, mot_de_passe_hache, role, telephone)
            )
            connexion.commit()
        except Exception:
            connexion.close()
            flash("Cet email est déjà utilisé.")
            return render_template("inscription.html", saisie=request.form)
        utilisateur = connexion.execute("SELECT * FROM utilisateurs WHERE email = ?", (email,)).fetchone()
        from routes.parrainage import parrain_du_code
        parrain_id = parrain_du_code(connexion, session.pop("parrain", None))
        if parrain_id and parrain_id != utilisateur["id"]:
            connexion.execute("UPDATE utilisateurs SET parrain_id = ? WHERE id = ?", (parrain_id, utilisateur["id"]))
            connexion.commit()
        connexion.close()

        if envoyer_lien_confirmation(utilisateur):
            flash("Compte créé avec succès, tu peux te connecter. "
                  "Un lien pour confirmer ton adresse e-mail vient de t'être envoyé.")
        else:
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


MESSAGE_COMPTE_SUSPENDU = "Ce compte est suspendu. Contacte l'administrateur de la plateforme."


@app.before_request
def deconnecter_compte_suspendu():
    """Un compte suspendu pendant qu'il est connecté est déconnecté à sa requête suivante."""
    if not utilisateur_connecte() or request.endpoint in (None, "static"):
        return None
    connexion_bd = get_connexion()
    utilisateur = connexion_bd.execute(
        "SELECT suspendu FROM utilisateurs WHERE id = ?", (session["utilisateur_id"],)
    ).fetchone()
    connexion_bd.close()
    if utilisateur is not None and utilisateur["suspendu"]:
        session.clear()
        flash(MESSAGE_COMPTE_SUSPENDU)
        return redirect(url_for("connexion"))
    return None


@app.route("/connexion", methods=["GET", "POST"])
def connexion():
    memoriser_page_suivante()
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

        if utilisateur["suspendu"]:
            flash(MESSAGE_COMPTE_SUSPENDU)
            return redirect(url_for("connexion"))

        session["utilisateur_id"] = utilisateur["id"]
        session["nom"] = utilisateur["nom"]
        session["role"] = utilisateur["role"]

        suivant = session.pop("suivant", None)
        if suivant:
            return redirect(suivant)

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


# Confirmation de l'adresse e-mail : le lien porte l'adresse confirmée, il ne vaut
# donc plus rien si l'utilisateur change d'adresse entre-temps.
DUREE_LIEN_CONFIRMATION = 7 * 24 * 60 * 60


def serialiseur_confirmation():
    return URLSafeTimedSerializer(app.secret_key, salt="confirmation-email")


def envoyer_lien_confirmation(utilisateur):
    jeton = serialiseur_confirmation().dumps({"id": utilisateur["id"], "email": utilisateur["email"]})
    lien = url_for("confirmer_email", jeton=jeton, _external=True)
    return envoyer_email(
        utilisateur["email"],
        "Confirmez votre adresse e-mail",
        f"<p>Bonjour {escape(utilisateur['nom'])},</p>"
        f"<p>Pour confirmer votre adresse e-mail sur App Agricole, cliquez sur ce lien (valable 7 jours) :</p>"
        f'<p><a href="{lien}">{lien}</a></p>'
        f"<p>Si vous n'avez pas créé de compte, ignorez cet e-mail.</p>",
    )


@app.route("/confirmer-email", methods=["POST"])
def renvoyer_confirmation_email():
    utilisateur = utilisateur_courant()
    if utilisateur is None:
        return redirect(url_for("connexion"))
    if email_confirme(utilisateur):
        flash("Ton adresse e-mail est déjà confirmée.")
    elif limite_atteinte(f"confirmation:{utilisateur['id']}", MAX_LIENS_PAR_EMAIL, UNE_HEURE):
        flash("Tu as déjà demandé plusieurs liens : vérifie tes e-mails (et les spams), ou réessaie dans une heure.")
    elif envoyer_lien_confirmation(utilisateur):
        flash(f"Un lien de confirmation a été envoyé à {utilisateur['email']}.")
    else:
        flash("L'e-mail n'a pas pu être envoyé. Réessaie plus tard.")
    return redirect(url_for("mon_profil"))


@app.route("/confirmer-email/<jeton>")
def confirmer_email(jeton):
    try:
        donnees = serialiseur_confirmation().loads(jeton, max_age=DUREE_LIEN_CONFIRMATION)
    except BadSignature:
        flash("Ce lien de confirmation est invalide ou a expiré.")
        return redirect(url_for("accueil"))

    connexion_bd = get_connexion()
    # Seulement si le compte a toujours l'adresse à laquelle le lien a été envoyé
    resultat = connexion_bd.execute(
        "UPDATE utilisateurs SET email_confirme = email WHERE id = ? AND email = ?",
        (donnees["id"], donnees["email"])
    )
    connexion_bd.commit()
    connexion_bd.close()
    if resultat.rowcount:
        flash("Adresse e-mail confirmée, merci !")
    else:
        flash("Ce lien ne correspond plus à l'adresse de ton compte.")
    return redirect(url_for("accueil"))


@app.route("/mot-de-passe-oublie", methods=["GET", "POST"])
def mot_de_passe_oublie():
    if request.method == "POST":
        email = request.form["email"].strip()

        connexion_bd = get_connexion()
        utilisateur = connexion_bd.execute(
            "SELECT * FROM utilisateurs WHERE email = ?", (email,)
        ).fetchone()
        connexion_bd.close()

        # Au-delà des limites, rien n'est envoyé, mais le message reste le même (on ne révèle
        # pas si l'adresse est inscrite)
        if (utilisateur
                and not limite_atteinte(f"reinitialisation-ip:{request.remote_addr}", MAX_LIENS_PAR_IP, UNE_HEURE)
                and not limite_atteinte(f"reinitialisation:{email.lower()}", MAX_LIENS_PAR_EMAIL, UNE_HEURE)):
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
        try:
            mot_de_passe_valide(mot_de_passe)
            if mot_de_passe != request.form["confirmation"]:
                raise ValueError("Les deux mots de passe doivent être identiques.")
        except ValueError as erreur:
            connexion_bd.close()
            flash(str(erreur))
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
    langue = session.get("langue")
    session.clear()
    if langue:
        session["langue"] = langue  # la langue choisie reste après la déconnexion
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

        try:
            if nouveau_mot_de_passe:
                mot_de_passe_valide(nouveau_mot_de_passe)
            telephone = telephone_valide(request.form.get("telephone", ""))
        except ValueError as erreur:
            connexion_bd.close()
            flash(str(erreur))
            return redirect(url_for("mon_profil"))

        if nouveau_mot_de_passe:
            mot_de_passe_a_enregistrer = generate_password_hash(nouveau_mot_de_passe)
        else:
            mot_de_passe_a_enregistrer = utilisateur["mot_de_passe"]

        try:
            connexion_bd.execute(
                "UPDATE utilisateurs SET nom = ?, email = ?, mot_de_passe = ?, telephone = ? WHERE id = ?",
                (nom, email, mot_de_passe_a_enregistrer, telephone, session["utilisateur_id"])
            )
            connexion_bd.commit()
        except Exception:
            connexion_bd.rollback()
            connexion_bd.close()
            flash("Cet email est déjà utilisé par un autre compte.")
            return redirect(url_for("mon_profil"))

        if email != utilisateur["email"]:
            # Nouvelle adresse : elle n'est plus confirmée, on envoie le lien tout de suite
            nouvel_utilisateur = connexion_bd.execute(
                "SELECT * FROM utilisateurs WHERE id = ?", (session["utilisateur_id"],)
            ).fetchone()
            envoyer_lien_confirmation(nouvel_utilisateur)
            flash("Un lien pour confirmer ta nouvelle adresse e-mail vient de t'être envoyé.")
        connexion_bd.close()
        session["nom"] = nom
        flash("Profil mis à jour avec succès.")
        return redirect(url_for("mon_profil"))

    connexion_bd.close()
    return render_template("mon_profil.html", utilisateur=utilisateur,
                           email_confirme=email_confirme(utilisateur))
