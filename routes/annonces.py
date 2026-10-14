"""Annonces publiques : page de chaque récolte, visible sans compte et partageable
(WhatsApp, Facebook...) avec aperçu (titre, prix, photo)."""
import base64
import hashlib
from datetime import date
from urllib.parse import quote

from flask import abort, render_template, request, Response, session, url_for
from database import get_connexion, COLONNES_RECOLTE
from core import app, utilisateur_connecte
from prix_marche import prix_du_marche, produit_cle
from routes.avis import NOTES_AGRICULTEURS


def recolte_publique(connexion_bd, recolte_id):
    return connexion_bd.execute(
        f"""SELECT {COLONNES_RECOLTE}, utilisateurs.nom AS nom_agriculteur,
                   utilisateurs.premium_jusqu_au AS premium_agriculteur,
                   notes.note_moyenne, notes.nb_avis
            FROM recoltes
            JOIN utilisateurs ON recoltes.agriculteur_id = utilisateurs.id
            LEFT JOIN {NOTES_AGRICULTEURS} notes ON notes.agriculteur_id = recoltes.agriculteur_id
            WHERE recoltes.id = ? AND utilisateurs.suspendu = 0""",
        (recolte_id,)
    ).fetchone()


def lien_partage_whatsapp(recolte):
    """Lien wa.me sans destinataire : l'agriculteur choisit à qui envoyer son annonce."""
    texte = (f"{recolte['nom']} disponible à {recolte['localite']} : {recolte['prix']}. "
             f"Commande sur App Agricole : {url_for('voir_annonce', recolte_id=recolte['id'], _external=True)}")
    return "https://wa.me/?text=" + quote(texte)


app.add_template_global(lien_partage_whatsapp)


@app.route("/annonce/<int:recolte_id>")
def voir_annonce(recolte_id):
    connexion_bd = get_connexion()
    recolte = recolte_publique(connexion_bd, recolte_id)
    if recolte is None:
        connexion_bd.close()
        abort(404)
    prix_courant = prix_du_marche(connexion_bd).get(produit_cle(recolte["nom"]))
    connexion_bd.close()
    return render_template(
        "annonce.html", recolte=recolte, prix_courant=prix_courant, aujourdhui=date.today().isoformat(),
        role=session.get("role") if utilisateur_connecte() else None,
    )


def reponse_photo(table, identifiant):
    """La photo (stockée en base64) en tant que fichier image, mise en cache par le navigateur."""
    connexion_bd = get_connexion()
    ligne = connexion_bd.execute(f"SELECT photo FROM {table} WHERE id = ?", (identifiant,)).fetchone()
    connexion_bd.close()
    photo = ligne["photo"] if ligne else None
    if not photo or not photo.startswith("data:image/") or ";base64," not in photo:
        abort(404)
    entete, donnees = photo.split(",", 1)
    reponse = Response(base64.b64decode(donnees), mimetype=entete[len("data:"):].split(";")[0])
    # Cache d'une heure ; ensuite le navigateur revérifie avec l'empreinte (ETag) et ne
    # retélécharge la photo que si elle a été remplacée
    reponse.headers["Cache-Control"] = "public, max-age=3600"
    reponse.set_etag(hashlib.md5(donnees.encode()).hexdigest())
    return reponse.make_conditional(request)


@app.route("/annonce/<int:recolte_id>/photo")
def photo_annonce(recolte_id):
    return reponse_photo("recoltes", recolte_id)


@app.route("/produit/<int:produit_id>/photo")
def photo_produit(produit_id):
    return reponse_photo("produits_fournisseur", produit_id)
