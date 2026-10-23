"""Application Flask, configuration et fonctions partagées par toutes les routes."""
import os
import re
import base64
import secrets
from functools import wraps
from flask import Flask, session, flash, redirect, request, url_for
from flask_wtf.csrf import CSRFProtect, CSRFError
from werkzeug.middleware.proxy_fix import ProxyFix
from database import UTILISE_POSTGRES, init_db

app = Flask(__name__)
# Derrière le proxy de Render : utilise https et le vrai nom de domaine dans les
# liens absolus (ex. lien de réinitialisation du mot de passe envoyé par e-mail)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
# Clé secrète des sessions : lue dans la variable d'environnement SECRET_KEY.
# En ligne (PostgreSQL), elle est obligatoire ; en local, une clé aléatoire est générée
# à chaque démarrage (il faudra simplement se reconnecter après un redémarrage).
app.secret_key = os.environ.get("SECRET_KEY")
if not app.secret_key:
    if UTILISE_POSTGRES:
        raise RuntimeError("La variable d'environnement SECRET_KEY doit être définie en production.")
    app.secret_key = secrets.token_hex(32)

# Protection CSRF : chaque formulaire POST doit renvoyer le jeton csrf_token()
# généré pour la session, ce qui empêche un autre site d'agir à la place d'un
# utilisateur connecté. Le jeton reste valable tant que la session est ouverte.
app.config["WTF_CSRF_TIME_LIMIT"] = None
csrf = CSRFProtect(app)

# Taille maximale d'une requête (photos comprises) : au-delà, refusée avant d'être lue
app.config["MAX_CONTENT_LENGTH"] = 9 * 1024 * 1024  # jusqu'à 4 photos de 2 Mo
# Cookie de session : jamais lisible en JavaScript, pas envoyé par les autres sites,
# et en ligne seulement en HTTPS
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = UTILISE_POSTGRES


@app.after_request
def entetes_de_securite(reponse):
    """En-têtes de sécurité : pas d'intégration du site dans une autre page (vol de clics),
    pas de devinette du type de fichier, adresse des pages non transmise aux autres sites."""
    reponse.headers.setdefault("X-Frame-Options", "DENY")
    reponse.headers.setdefault("X-Content-Type-Options", "nosniff")
    reponse.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    # Pas de plugins (Flash, Java…), pas de balise <base> injectée pour détourner les liens
    reponse.headers.setdefault("Content-Security-Policy", "object-src 'none'; base-uri 'self'; frame-ancestors 'none'")
    if UTILISE_POSTGRES:  # en ligne, toujours en HTTPS
        reponse.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return reponse


@app.errorhandler(413)
def requete_trop_grosse(erreur):
    flash("Le fichier envoyé est trop volumineux (9 Mo maximum par envoi).")
    return redirect(request.referrer if request.referrer and request.referrer.startswith(request.host_url)
                    else url_for("accueil"))


def limite_atteinte(cle, maximum, duree_secondes):
    """Vrai si l'action `cle` a déjà eu lieu `maximum` fois pendant `duree_secondes` ; sinon
    l'enregistre. Sert à limiter les envois d'e-mails (quota Brevo) et les inscriptions."""
    import time
    from database import get_connexion
    maintenant = int(time.time())
    connexion_bd = get_connexion()
    connexion_bd.execute("DELETE FROM limites_envoi WHERE instant <= ?", (maintenant - 24 * 3600,))
    nombre = connexion_bd.execute(
        "SELECT COUNT(*) AS n FROM limites_envoi WHERE cle = ? AND instant > ?", (cle, maintenant - duree_secondes)
    ).fetchone()["n"]
    if nombre < maximum:
        connexion_bd.execute("INSERT INTO limites_envoi (cle, instant) VALUES (?, ?)", (cle, maintenant))
    connexion_bd.commit()
    connexion_bd.close()
    return nombre >= maximum


@app.errorhandler(404)
def page_introuvable(erreur):
    from flask import render_template
    return render_template("erreur.html", titre="Page introuvable",
                           message="Cette page n'existe pas ou n'est plus disponible."), 404


@app.errorhandler(500)
def erreur_serveur(erreur):
    # Le détail de l'erreur part dans les journaux de Render ; l'utilisateur voit une page propre
    from flask import render_template
    app.logger.exception("Erreur pendant la requête %s", request.path)
    try:
        return render_template("erreur.html", titre="Un problème est survenu",
                               message="Réessaie dans un instant. Si le problème continue, contacte-nous."), 500
    except Exception:
        # Si même la page d'erreur échoue (ex : base de données indisponible), page minimale
        return "<h2>Un problème est survenu</h2><p>Réessaie dans un instant.</p>", 500


@app.errorhandler(CSRFError)
def jeton_csrf_invalide(erreur):
    flash("Votre session a expiré ou le formulaire n'est plus valide. Merci de réessayer.")
    # On ne renvoie vers la page précédente que si elle appartient à ce site
    page_precedente = request.referrer or ""
    if not page_precedente.startswith(request.host_url):
        page_precedente = url_for("accueil")
    return redirect(page_precedente)


EXTENSIONS_AUTORISEES = {"png", "jpg", "jpeg", "webp"}
TAILLE_MAX_PHOTO = 2 * 1024 * 1024  # 2 Mo, pour garder la base de données légère

init_db()


def extension_autorisee(nom_fichier):
    return "." in nom_fichier and nom_fichier.rsplit(".", 1)[1].lower() in EXTENSIONS_AUTORISEES


def encoder_photo(fichier):
    """
    Encode une photo envoyée en formulaire directement en base64 pour la stocker
    dans la base de données (au lieu du disque, qui n'est pas permanent en ligne).
    Retourne une chaîne "data:image/...;base64,...." prête à être utilisée dans un
    attribut src d'image, ou None si aucune photo valide n'a été envoyée.
    """
    if not fichier or not fichier.filename or not extension_autorisee(fichier.filename):
        return None

    contenu = fichier.read()
    if len(contenu) > TAILLE_MAX_PHOTO:
        flash("La photo est trop volumineuse (2 Mo maximum) et n'a pas été enregistrée.")
        return None

    # On se fie au contenu réel du fichier, pas à son nom
    if contenu.startswith(b"\xff\xd8\xff"):
        type_mime = "image/jpeg"
    elif contenu.startswith(b"\x89PNG\r\n\x1a\n"):
        type_mime = "image/png"
    elif contenu[:4] == b"RIFF" and contenu[8:12] == b"WEBP":
        type_mime = "image/webp"
    else:
        flash("Le fichier envoyé n'est pas une image valide (JPG, PNG ou WEBP).")
        return None

    photo_base64 = base64.b64encode(contenu).decode("utf-8")
    return f"data:{type_mime};base64,{photo_base64}"


# Un nombre positif suivi d'une unité facultative : "20 kg", "100 sachets", "1,5 tonne"
MOTIF_QUANTITE = re.compile(r"^\d+(?:[.,]\d+)?(?:\s*[^\W\d_]+\.?)*$")
# Un prix en chiffres, FCFA facultatif, unité facultative : "500 FCFA / kg", "1 500 F", "2000"
MOTIF_PRIX = re.compile(r"^\d[\d ]*(?:[.,]\d+)?\s*(?:F\s*CFA|FCFA|CFA|F)?\s*(?:/\s*[^\W\d_]+)?$", re.IGNORECASE)


def quantite_valide(texte):
    """Retourne la quantité nettoyée, ou lève ValueError si elle n'est pas chiffrée."""
    texte = " ".join((texte or "").split())
    if not MOTIF_QUANTITE.match(texte) or float(re.match(r"[\d.,]+", texte).group().replace(",", ".")) <= 0:
        raise ValueError("La quantité doit être un nombre positif suivi d'une unité (ex: 20 kg).")
    return texte


def prix_valide(texte):
    """Retourne le prix nettoyé, ou lève ValueError s'il n'est pas chiffré."""
    texte = " ".join((texte or "").split())
    if not MOTIF_PRIX.match(texte) or not any(c in "123456789" for c in re.match(r"[\d ]+", texte).group()):
        raise ValueError("Le prix doit être un montant positif (ex: 500 FCFA / kg).")
    return texte


def utilisateur_connecte():
    return "utilisateur_id" in session



ROLES = ("client", "agriculteur", "fournisseur", "financeur")
LONGUEUR_MIN_MOT_DE_PASSE = 8


def mot_de_passe_valide(mot_de_passe):
    """Lève ValueError si le mot de passe est trop court."""
    if len(mot_de_passe or "") < LONGUEUR_MIN_MOT_DE_PASSE:
        raise ValueError(f"Le mot de passe doit contenir au moins {LONGUEUR_MIN_MOT_DE_PASSE} caractères.")
    return mot_de_passe


def telephone_valide(texte):
    """Retourne le numéro nettoyé (ou None s'il est vide), ou lève ValueError s'il est invalide."""
    texte = " ".join((texte or "").split())
    if not texte:
        return None
    chiffres = re.sub(r"\D", "", texte)
    if not re.fullmatch(r"\+?[\d .\-()]+", texte) or not 8 <= len(chiffres) <= 15:
        raise ValueError("Le numéro de téléphone doit contenir entre 8 et 15 chiffres (ex: 77 123 45 67).")
    return texte


MOTIF_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Suite d'au moins 8 chiffres, éventuellement séparés par des espaces ou des points
# (77 123 45 67, +221 77..., 0022177...) ; les quantités et prix restent visibles
MOTIF_TELEPHONE = re.compile(r"\+?\d(?:[\s.]*\d){7,}")


def masquer_coordonnees(texte):
    """Masque téléphones et e-mails dans un message libre, pour que clients et agriculteurs
    ne contournent pas la plateforme (et sa commission)."""
    texte = MOTIF_EMAIL.sub("[e-mail masqué]", texte or "")
    return MOTIF_TELEPHONE.sub("[numéro masqué]", texte)


@app.template_filter("whatsapp")
def lien_whatsapp(telephone):
    """Numéro -> lien wa.me. Un numéro sénégalais local (9 chiffres, 7x) reçoit l'indicatif 221."""
    chiffres = re.sub(r"\D", "", telephone or "")
    if chiffres.startswith("00"):
        chiffres = chiffres[2:]
    if len(chiffres) == 9 and chiffres.startswith("7"):
        chiffres = "221" + chiffres
    return f"https://wa.me/{chiffres}"


# --- Modèle économique ---------------------------------------------------------
# Tous les montants sont en FCFA. Valeurs modifiables par variables d'environnement.
TAUX_COMMISSION = float(os.environ.get("TAUX_COMMISSION", "0.05"))           # 5 % des ventes livrées
PRIX_PREMIUM_MENSUEL = int(os.environ.get("PRIX_PREMIUM_MENSUEL", "3000"))    # abonnement de 30 jours
DUREE_PREMIUM_JOURS = 30
NUMERO_PAIEMENT = os.environ.get("NUMERO_PAIEMENT", "")                       # numéro Wave / Orange Money
EMAILS_ADMIN = {e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()}


def calculer_commission(montant):
    return round(montant * TAUX_COMMISSION)


def montant_valide(texte):
    """Montant entier positif en FCFA (espaces et points de milliers acceptés)."""
    chiffres = re.sub(r"[\s.]", "", texte or "").upper().replace("FCFA", "").replace("F", "")
    if not chiffres.isdigit() or int(chiffres) <= 0:
        raise ValueError("Indique le montant de la vente en FCFA (ex: 25000).")
    return int(chiffres)


# --- Livraison -----------------------------------------------------------------
MODES_LIVRAISON = {"retrait": "Retrait chez l'agriculteur", "livraison": "Livraison à domicile"}
LONGUEUR_MAX_ADRESSE = 300
MODES_PAIEMENT = {"livraison": "Paiement à la livraison", "wave": "Paiement en ligne avec Wave"}


def mode_paiement_valide(formulaire):
    """'wave' seulement si le paiement Wave est configuré ; sinon paiement à la livraison."""
    import wave
    mode = formulaire.get("mode_paiement", "livraison")
    return "wave" if mode == "wave" and wave.wave_active() else "livraison"


def livraison_valide(formulaire):
    """Retourne (mode, adresse) d'après le formulaire de commande, ou lève ValueError."""
    mode = formulaire.get("mode_livraison", "retrait")
    adresse = " ".join(formulaire.get("adresse_livraison", "").split())
    if mode not in MODES_LIVRAISON:
        raise ValueError("Choisis un mode de livraison.")
    if mode == "retrait":
        return mode, None
    if not adresse:
        raise ValueError("Indique l'adresse de livraison (quartier, ville, repère).")
    if len(adresse) > LONGUEUR_MAX_ADRESSE:
        raise ValueError(f"L'adresse ne doit pas dépasser {LONGUEUR_MAX_ADRESSE} caractères.")
    return mode, adresse


def planning_livraison_valide(formulaire):
    """Date prévue (AAAA-MM-JJ) et frais de livraison (FCFA), tous deux facultatifs."""
    from datetime import date
    date_prevue = formulaire.get("date_livraison_prevue", "").strip() or None
    if date_prevue:
        try:
            date_prevue = date.fromisoformat(date_prevue).isoformat()
        except ValueError:
            raise ValueError("La date de livraison prévue n'est pas valide.")
    frais = re.sub(r"[\s.]", "", formulaire.get("frais_livraison", "")).upper().replace("FCFA", "").replace("F", "")
    if frais and not frais.isdigit():
        raise ValueError("Les frais de livraison doivent être un montant en FCFA (ex: 1500).")
    return date_prevue, int(frais) if frais else None


@app.template_filter("date_fr")
def date_fr(valeur):
    """'2026-11-05' -> '05/11/2026'."""
    try:
        annee, mois, jour = str(valeur)[:10].split("-")
        return f"{jour}/{mois}/{annee}"
    except ValueError:
        return valeur


HORIZON_PRECOMMANDE_JOURS = 365  # une récolte peut être annoncée jusqu'à un an à l'avance


def date_disponibilite_valide(texte):
    """AAAA-MM-JJ ; une date future fait de l'annonce une récolte « à venir » (pré-commandes)."""
    from datetime import date, timedelta
    try:
        jour = date.fromisoformat((texte or "").strip())
    except ValueError:
        raise ValueError("Indique la date de disponibilité de la récolte.")
    if jour > date.today() + timedelta(days=HORIZON_PRECOMMANDE_JOURS):
        raise ValueError("La récolte ne peut pas être annoncée plus d'un an à l'avance.")
    return jour.isoformat()


@app.template_global()
def a_venir(date_disponibilite):
    """Vrai si la récolte n'est pas encore prête : elle se réserve (pré-commande)."""
    from datetime import date
    return str(date_disponibilite or "")[:10] > date.today().isoformat()


def date_fin_premium(utilisateur):
    """Date de fin d'abonnement (objet date) si l'utilisateur est Premium aujourd'hui, sinon None."""
    from datetime import date
    valeur = utilisateur["premium_jusqu_au"] if utilisateur else None
    if not valeur:
        return None
    fin = date.fromisoformat(str(valeur)[:10])
    return fin if fin >= date.today() else None


def utilisateur_courant():
    """Ligne de l'utilisateur connecté (ou None)."""
    if not utilisateur_connecte():
        return None
    from database import get_connexion
    connexion_bd = get_connexion()
    utilisateur = connexion_bd.execute(
        "SELECT * FROM utilisateurs WHERE id = ?", (session["utilisateur_id"],)
    ).fetchone()
    connexion_bd.close()
    return utilisateur


def est_premium():
    return date_fin_premium(utilisateur_courant()) is not None


def email_confirme(utilisateur):
    """Vrai si l'adresse actuelle du compte a été confirmée par le lien envoyé par e-mail."""
    email = (utilisateur["email"] or "").strip().lower()
    return bool(email) and (utilisateur["email_confirme"] or "").strip().lower() == email


def adresse_admin(utilisateur):
    return bool(utilisateur) and (utilisateur["email"] or "").strip().lower() in EMAILS_ADMIN


def est_admin(utilisateur=None):
    """Administrateur : adresse listée dans ADMIN_EMAILS ET confirmée (sinon n'importe qui
    pourrait s'inscrire, ou modifier son profil, avec une adresse admin)."""
    utilisateur = utilisateur or utilisateur_courant()
    return adresse_admin(utilisateur) and email_confirme(utilisateur)


def premium_requis(vue):
    """Réserve une page aux abonnés Premium ; les autres sont envoyés vers la page d'abonnement."""
    @wraps(vue)
    def vue_protegee(*args, **kwargs):
        if utilisateur_connecte() and not est_premium():
            flash("Cette fonctionnalité est réservée aux membres Premium.")
            return redirect(url_for("premium"))
        return vue(*args, **kwargs)
    return vue_protegee


@app.context_processor
def injecter_statut_compte():
    """Rend le statut Premium / administrateur disponible dans tous les templates."""
    utilisateur = utilisateur_courant()
    return {
        "fin_premium": date_fin_premium(utilisateur),
        # Le lien Admin s'affiche aussi avant confirmation, pour guider vers la confirmation
        "est_admin": adresse_admin(utilisateur),
    }
