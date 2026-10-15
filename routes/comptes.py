"""Accueil, inscription, connexion et profil."""
import secrets
import time
from datetime import date

from flask import render_template, request, redirect, url_for, session, flash
from itsdangerous import URLSafeTimedSerializer, BadSignature
from markupsafe import escape
from werkzeug.security import generate_password_hash, check_password_hash
import sms
from database import get_connexion
from emails import envoyer_email
from core import (app, utilisateur_connecte, mot_de_passe_valide, telephone_valide, ROLES,
                  utilisateur_courant, email_confirme, limite_atteinte, MOTIF_EMAIL)
from geographie import (PAYS, SENEGAL, AUTRE, PAYS_PAR_DEFAUT, lieu_valide, telephone_international)

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
    from routes.vitrine import page_accueil
    return page_accueil()


def memoriser_page_suivante():
    """Mémorise la page où aller après la connexion (ex: commander depuis une annonce partagée).
    Seulement un chemin de ce site, pour ne jamais rediriger vers un site extérieur."""
    suivant = request.args.get("suivant", "")
    if suivant.startswith("/") and not suivant.startswith(("//", "/\\")):
        session["suivant"] = suivant


def formulaire_inscription(saisie):
    return render_template("inscription.html", saisie=saisie, pays=PAYS, senegal=SENEGAL, autre=AUTRE)


@app.route("/inscription", methods=["GET", "POST"])
def inscription():
    # Rôle présélectionné depuis la page d'accueil (« Je vends mes récoltes »)
    role_propose = request.args.get("role") if request.args.get("role") in ROLES else None
    memoriser_page_suivante()
    if request.args.get("parrain"):
        session["parrain"] = request.args["parrain"][:20]
    if request.method == "POST":
        nom = " ".join(request.form.get("nom", "").split())
        mode = "telephone" if request.form.get("mode") == "telephone" else "email"
        mot_de_passe = request.form["mot_de_passe"]
        role = request.form.get("role", "")

        connexion = get_connexion()
        try:
            if not nom:
                raise ValueError("Indique ton nom.")
            if role not in ROLES:
                raise ValueError("Choisis un type de compte dans la liste.")
            lieu = lieu_valide(request.form)
            if mode == "telephone":
                # Le numéro sert d'identifiant : un seul compte par numéro
                telephone = telephone_international(request.form.get("telephone", ""), lieu["pays"])
                if connexion.execute("SELECT id FROM utilisateurs WHERE telephone_connexion = ?",
                                     (telephone,)).fetchone():
                    raise ValueError("Ce numéro de téléphone est déjà utilisé : connecte-toi avec.")
                email, telephone_connexion = None, telephone
            else:
                email = request.form.get("email", "").strip()
                if not MOTIF_EMAIL.fullmatch(email):
                    raise ValueError("Adresse e-mail invalide.")
                telephone, telephone_connexion = telephone_valide(request.form.get("telephone", "")), None
            mot_de_passe_valide(mot_de_passe)
        except ValueError as erreur:
            connexion.close()
            flash(str(erreur))
            return formulaire_inscription(request.form)

        if limite_atteinte(f"inscription-ip:{request.remote_addr}", MAX_INSCRIPTIONS_PAR_IP, UNE_HEURE):
            connexion.close()
            flash("Trop de comptes créés depuis cette connexion. Réessaie dans une heure.")
            return formulaire_inscription(request.form)

        try:
            utilisateur_id = connexion.execute(
                """INSERT INTO utilisateurs (nom, email, mot_de_passe, role, telephone, telephone_connexion,
                                            date_inscription, pays, region, departement, commune, localite)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id""",
                (nom, email, generate_password_hash(mot_de_passe), role, telephone, telephone_connexion,
                 date.today().isoformat(), lieu["pays"], lieu["region"], lieu["departement"], lieu["commune"],
                 lieu["localite"])
            ).fetchone()["id"]
            connexion.commit()
        except Exception:
            connexion.rollback()
            connexion.close()
            flash("Cet email est déjà utilisé." if mode == "email" else "Ce numéro de téléphone est déjà utilisé.")
            return formulaire_inscription(request.form)
        utilisateur = connexion.execute("SELECT * FROM utilisateurs WHERE id = ?", (utilisateur_id,)).fetchone()
        from routes.parrainage import parrain_du_code
        parrain_id = parrain_du_code(connexion, session.pop("parrain", None))
        if parrain_id and parrain_id != utilisateur["id"]:
            connexion.execute("UPDATE utilisateurs SET parrain_id = ? WHERE id = ?", (parrain_id, utilisateur["id"]))
            connexion.commit()
        connexion.close()

        if email and envoyer_lien_confirmation(utilisateur):
            flash("Compte créé avec succès, tu peux te connecter. "
                  "Un lien pour confirmer ton adresse e-mail vient de t'être envoyé.")
        elif mode == "telephone":
            flash("Compte créé avec succès : connecte-toi avec ton numéro de téléphone et ton mot de passe.")
        else:
            flash("Compte créé avec succès, tu peux te connecter.")
        return redirect(url_for("connexion"))

    saisie = {"pays": PAYS_PAR_DEFAUT, "mode": request.args.get("mode", "telephone")}
    if role_propose:
        saisie["role"] = role_propose
    return formulaire_inscription(saisie)


def utilisateur_par_identifiant(connexion_bd, identifiant):
    """Compte correspondant à un e-mail ou à un numéro de téléphone (None sinon)."""
    identifiant = identifiant.strip()
    if "@" in identifiant:
        return connexion_bd.execute("SELECT * FROM utilisateurs WHERE email = ?", (identifiant,)).fetchone()
    try:
        telephone = telephone_international(identifiant)
    except ValueError:
        return None
    return connexion_bd.execute("SELECT * FROM utilisateurs WHERE telephone_connexion = ?", (telephone,)).fetchone()


def cle_identifiant(identifiant):
    """Clé des tentatives échouées : l'e-mail en minuscules, ou le numéro au format international."""
    identifiant = identifiant.strip().lower()
    if "@" in identifiant:
        return identifiant
    try:
        return telephone_international(identifiant)
    except ValueError:
        return identifiant


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
        identifiant = request.form.get("identifiant") or request.form.get("email", "")
        mot_de_passe = request.form["mot_de_passe"]
        cle_echecs = cle_identifiant(identifiant)

        connexion_bd = get_connexion()
        if nombre_echecs_recents(connexion_bd, cle_echecs) >= MAX_ECHECS:
            connexion_bd.close()
            flash("Trop de tentatives de connexion pour ce compte. Réessayez dans 15 minutes.")
            return redirect(url_for("connexion"))

        utilisateur = utilisateur_par_identifiant(connexion_bd, identifiant)

        if not (utilisateur and check_password_hash(utilisateur["mot_de_passe"], mot_de_passe)):
            enregistrer_echec(connexion_bd, cle_echecs)
            connexion_bd.close()
            flash("Email / téléphone ou mot de passe incorrect.")
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
        identifiant = (request.form.get("identifiant") or request.form.get("email", "")).strip()
        if identifiant and "@" not in identifiant:
            return envoyer_code_sms(identifiant)
        email = identifiant

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


# Mot de passe oublié pour un compte créé avec un téléphone : un code à 6 chiffres est envoyé
# par SMS (valable 15 minutes, 5 essais). Seule son empreinte est gardée en base.
DUREE_CODE_SMS = 15 * 60
MAX_ESSAIS_CODE = 5
MAX_CODES_PAR_NUMERO = 3


def envoyer_code_sms(identifiant):
    if not sms.sms_actif():
        flash("La réinitialisation par SMS n'est pas encore disponible. Écris-nous depuis la page Contact.")
        return redirect(url_for("contact"))
    try:
        telephone = telephone_international(identifiant)
    except ValueError:
        flash("Numéro de téléphone invalide (ex : 77 123 45 67).")
        return redirect(url_for("mot_de_passe_oublie"))

    connexion_bd = get_connexion()
    utilisateur = connexion_bd.execute(
        "SELECT id FROM utilisateurs WHERE telephone_connexion = ? AND suspendu = 0", (telephone,)).fetchone()
    # Au-delà des limites, rien n'est envoyé, mais la suite est la même (on ne révèle pas si le
    # numéro est inscrit)
    if (utilisateur
            and not limite_atteinte(f"reinitialisation-ip:{request.remote_addr}", MAX_LIENS_PAR_IP, UNE_HEURE)
            and not limite_atteinte(f"code-sms:{telephone}", MAX_CODES_PAR_NUMERO, UNE_HEURE)):
        code = f"{secrets.randbelow(1_000_000):06d}"
        connexion_bd.execute("DELETE FROM codes_sms WHERE utilisateur_id = ?", (utilisateur["id"],))
        connexion_bd.execute(
            "INSERT INTO codes_sms (utilisateur_id, empreinte, expire_a) VALUES (?, ?, ?)",
            (utilisateur["id"], generate_password_hash(code), int(time.time()) + DUREE_CODE_SMS))
        connexion_bd.commit()
        sms.envoyer_sms(telephone, f"App Agricole : ton code est {code}. Valable 15 minutes. "
                                   "Ne le donne a personne.")
    connexion_bd.close()
    session["reinitialisation_telephone"] = telephone
    flash("Si un compte existe avec ce numéro, un code vient d'être envoyé par SMS.")
    return redirect(url_for("reinitialiser_par_sms"))


@app.route("/reinitialiser-par-sms", methods=["GET", "POST"])
def reinitialiser_par_sms():
    telephone = session.get("reinitialisation_telephone")
    if not telephone:
        return redirect(url_for("mot_de_passe_oublie"))
    if request.method == "POST":
        code = "".join(request.form.get("code", "").split())
        mot_de_passe = request.form.get("mot_de_passe", "")
        try:
            mot_de_passe_valide(mot_de_passe)
            if mot_de_passe != request.form.get("confirmation", ""):
                raise ValueError("Les deux mots de passe doivent être identiques.")
        except ValueError as erreur:
            flash(str(erreur))
            return redirect(url_for("reinitialiser_par_sms"))

        connexion_bd = get_connexion()
        ligne = connexion_bd.execute(
            """SELECT codes_sms.id, codes_sms.empreinte, codes_sms.expire_a, codes_sms.essais, utilisateurs.id AS uid
               FROM codes_sms JOIN utilisateurs ON codes_sms.utilisateur_id = utilisateurs.id
               WHERE utilisateurs.telephone_connexion = ?""", (telephone,)).fetchone()
        valide = (ligne is not None and ligne["expire_a"] > time.time() and ligne["essais"] < MAX_ESSAIS_CODE
                  and check_password_hash(ligne["empreinte"], code))
        if not valide:
            if ligne is not None:
                connexion_bd.execute("UPDATE codes_sms SET essais = essais + 1 WHERE id = ?", (ligne["id"],))
                connexion_bd.commit()
            connexion_bd.close()
            flash("Code incorrect ou expiré. Vérifie le SMS, ou demande un nouveau code.")
            return redirect(url_for("reinitialiser_par_sms"))
        connexion_bd.execute("UPDATE utilisateurs SET mot_de_passe = ? WHERE id = ?",
                             (generate_password_hash(mot_de_passe), ligne["uid"]))
        connexion_bd.execute("DELETE FROM codes_sms WHERE id = ?", (ligne["id"],))
        connexion_bd.execute("DELETE FROM echecs_connexion WHERE email = ?", (telephone,))
        connexion_bd.commit()
        connexion_bd.close()
        session.pop("reinitialisation_telephone", None)
        flash("Mot de passe modifié, tu peux te connecter.")
        return redirect(url_for("connexion"))
    return render_template("reinitialiser_par_sms.html", telephone=telephone)


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
            "DELETE FROM echecs_connexion WHERE email = ?", ((utilisateur["email"] or "").strip().lower(),)
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

        par_telephone = bool(utilisateur["telephone_connexion"])
        telephone_connexion = utilisateur["telephone_connexion"]
        try:
            if nouveau_mot_de_passe:
                mot_de_passe_valide(nouveau_mot_de_passe)
            lieu = lieu_valide(request.form)
            email = email.strip() or None
            if email and not MOTIF_EMAIL.fullmatch(email):
                raise ValueError("Adresse e-mail invalide.")
            if par_telephone:
                # Le numéro sert à se connecter : obligatoire et propre à ce compte
                telephone = telephone_connexion = telephone_international(request.form.get("telephone", ""),
                                                                          lieu["pays"])
                if connexion_bd.execute("SELECT id FROM utilisateurs WHERE telephone_connexion = ? AND id <> ?",
                                        (telephone, utilisateur["id"])).fetchone():
                    raise ValueError("Ce numéro de téléphone est déjà utilisé par un autre compte.")
            else:
                if not email:
                    raise ValueError("Indique ton adresse e-mail.")
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
                """UPDATE utilisateurs SET nom = ?, email = ?, mot_de_passe = ?, telephone = ?, telephone_connexion = ?,
                                          pays = ?, region = ?, departement = ?, commune = ?, localite = ?
                   WHERE id = ?""",
                (nom, email, mot_de_passe_a_enregistrer, telephone, telephone_connexion, lieu["pays"],
                 lieu["region"], lieu["departement"], lieu["commune"], lieu["localite"], session["utilisateur_id"])
            )
            connexion_bd.commit()
        except Exception:
            connexion_bd.rollback()
            connexion_bd.close()
            flash("Cet email est déjà utilisé par un autre compte.")
            return redirect(url_for("mon_profil"))

        if email and email != utilisateur["email"]:
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
    saisie = {cle: utilisateur[cle] or "" for cle in ("pays", "region", "departement", "commune", "localite")}
    saisie["pays"] = saisie["pays"] or PAYS_PAR_DEFAUT
    return render_template("mon_profil.html", utilisateur=utilisateur, email_confirme=email_confirme(utilisateur),
                           saisie=saisie, pays=PAYS, senegal=SENEGAL, autre=AUTRE)
