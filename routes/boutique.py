"""Boutique publique d'un agriculteur (toutes ses annonces sur une page) et son affiche à QR code.

L'agriculteur imprime l'affiche et la pose sur son étal au marché : en scannant le QR code, les
passants arrivent sur sa boutique et peuvent commander ou le suivre."""
import io
from datetime import date

import segno
from flask import abort, render_template, Response, redirect, session, url_for

from database import get_connexion, COLONNES_RECOLTE
from core import app, utilisateur_connecte
from routes.avis import NOTES_AGRICULTEURS
from routes.favoris import suit


def agriculteur_public(connexion_bd, agriculteur_id):
    return connexion_bd.execute(
        f"""SELECT utilisateurs.id, utilisateurs.nom, utilisateurs.verification, utilisateurs.date_inscription,
                   utilisateurs.premium_jusqu_au, notes.note_moyenne, notes.nb_avis
            FROM utilisateurs LEFT JOIN {NOTES_AGRICULTEURS} notes ON notes.agriculteur_id = utilisateurs.id
            WHERE utilisateurs.id = ? AND utilisateurs.role = 'agriculteur' AND utilisateurs.suspendu = 0""",
        (agriculteur_id,)
    ).fetchone()


def annonces_en_ligne(connexion_bd, agriculteur_id):
    return connexion_bd.execute(
        f"""SELECT {COLONNES_RECOLTE}, utilisateurs.nom AS nom_agriculteur,
                   utilisateurs.premium_jusqu_au AS premium_agriculteur,
                   utilisateurs.verification AS verification_agriculteur,
                   notes.note_moyenne, notes.nb_avis
            FROM recoltes
            JOIN utilisateurs ON recoltes.agriculteur_id = utilisateurs.id
            LEFT JOIN {NOTES_AGRICULTEURS} notes ON notes.agriculteur_id = recoltes.agriculteur_id
            WHERE recoltes.agriculteur_id = ? AND recoltes.statut = 'disponible' AND recoltes.masquee = 0
            ORDER BY recoltes.id DESC""",
        (agriculteur_id,)
    ).fetchall()


@app.route("/producteurs/<int:agriculteur_id>")
def boutique(agriculteur_id):
    connexion_bd = get_connexion()
    agriculteur = agriculteur_public(connexion_bd, agriculteur_id)
    if agriculteur is None:
        connexion_bd.close()
        abort(404)
    recoltes = annonces_en_ligne(connexion_bd, agriculteur_id)
    derniers_avis = connexion_bd.execute(
        """SELECT avis.note, avis.commentaire, avis.date_creation, utilisateurs.nom AS nom_client
           FROM avis JOIN utilisateurs ON avis.client_id = utilisateurs.id
           WHERE avis.agriculteur_id = ? AND avis.commentaire IS NOT NULL
           ORDER BY avis.id DESC LIMIT 3""",
        (agriculteur_id,)
    ).fetchall()
    livraisons = connexion_bd.execute(
        """SELECT COUNT(*) AS n FROM commandes JOIN recoltes ON commandes.recolte_id = recoltes.id
           WHERE recoltes.agriculteur_id = ? AND commandes.statut = 'livree'""", (agriculteur_id,)
    ).fetchone()["n"]
    suivi = suit(connexion_bd, agriculteur_id)
    connexion_bd.close()
    role = session.get("role") if utilisateur_connecte() else None
    return render_template("boutique.html", agriculteur=agriculteur, recoltes=recoltes, derniers_avis=derniers_avis,
                           livraisons=livraisons, suivi=suivi, role=role,
                           localites=sorted({r["localite"] for r in recoltes}),
                           aujourdhui=date.today().isoformat())


@app.route("/producteurs/<int:agriculteur_id>/qr.svg")
def qr_boutique(agriculteur_id):
    """QR code (SVG) menant à la boutique : net à toutes les tailles, à l'écran comme à l'impression."""
    connexion_bd = get_connexion()
    agriculteur = agriculteur_public(connexion_bd, agriculteur_id)
    connexion_bd.close()
    if agriculteur is None:
        abort(404)
    qr = segno.make(url_for("boutique", agriculteur_id=agriculteur_id, _external=True), error="m")
    tampon = io.BytesIO()
    qr.save(tampon, kind="svg", scale=10, dark="#14532d", border=2, xmldecl=False)  # SVG autonome (avec xmlns)
    reponse = Response(tampon.getvalue(), mimetype="image/svg+xml")
    reponse.headers["Cache-Control"] = "public, max-age=86400"
    return reponse


@app.route("/espace-agriculteur/affiche")
def affiche_boutique():
    if not utilisateur_connecte() or session["role"] != "agriculteur":
        return redirect(url_for("connexion"))
    connexion_bd = get_connexion()
    agriculteur = agriculteur_public(connexion_bd, session["utilisateur_id"])
    recoltes = annonces_en_ligne(connexion_bd, session["utilisateur_id"]) if agriculteur else []
    connexion_bd.close()
    if agriculteur is None:
        abort(404)
    return render_template("affiche_boutique.html", agriculteur=agriculteur, recoltes=recoltes[:8])
