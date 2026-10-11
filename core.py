"""Application Flask, configuration et fonctions partagées par toutes les routes."""
import os
import re
import base64
import secrets
from flask import Flask, session, flash
from database import UTILISE_POSTGRES, init_db

app = Flask(__name__)
# Clé secrète des sessions : lue dans la variable d'environnement SECRET_KEY.
# En ligne (PostgreSQL), elle est obligatoire ; en local, une clé aléatoire est générée
# à chaque démarrage (il faudra simplement se reconnecter après un redémarrage).
app.secret_key = os.environ.get("SECRET_KEY")
if not app.secret_key:
    if UTILISE_POSTGRES:
        raise RuntimeError("La variable d'environnement SECRET_KEY doit être définie en production.")
    app.secret_key = secrets.token_hex(32)

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

