"""Assistant IA pour les agriculteurs : rédaction d'annonce et conseiller agricole (voir ia.py).
Nombre de demandes limité par jour et par compte, pour maîtriser le coût de l'API."""
from flask import jsonify, redirect, render_template, request, session, url_for

import ia
from database import get_connexion
from core import app, encoder_photo, est_premium, limite_atteinte, utilisateur_connecte
from prix_marche import prix_du_marche, produit_cle

QUOTA_JOUR = 15
QUOTA_JOUR_PREMIUM = 50
LONGUEUR_MAX = 1000


@app.context_processor
def assistant_ia():
    return {"ia_active": ia.ia_active()}


def agriculteur_connecte():
    return utilisateur_connecte() and session.get("role") == "agriculteur"


def quota_depasse():
    quota = QUOTA_JOUR_PREMIUM if est_premium() else QUOTA_JOUR
    return limite_atteinte(f"ia:{session['utilisateur_id']}", quota, 24 * 3600)


@app.route("/ia/annonce", methods=["POST"])
def ia_rediger_annonce():
    if not agriculteur_connecte():
        return jsonify({"erreur": "Connecte-toi en tant qu'agriculteur."}), 401
    donnees = request.get_json(silent=True) or {}
    produit = str(donnees.get("nom", "")).strip()[:100]
    if not produit:
        return jsonify({"erreur": "Indique d'abord le nom du produit."}), 400
    if quota_depasse():
        return jsonify({"erreur": "Tu as utilisé toutes tes demandes à l'assistant pour aujourd'hui."}), 429
    connexion_bd = get_connexion()
    marche = prix_du_marche(connexion_bd).get(produit_cle(produit))
    connexion_bd.close()
    try:
        texte = ia.rediger_annonce(produit, str(donnees.get("quantite", ""))[:50], str(donnees.get("localite", ""))[:100],
                                   str(donnees.get("description", ""))[:LONGUEUR_MAX],
                                   marche["median"] if marche else None)
    except ia.IAIndisponible as erreur:
        return jsonify({"erreur": str(erreur)}), 503
    return jsonify({"texte": texte})


@app.route("/espace-agriculteur/conseiller", methods=["GET", "POST"])
def conseiller_agricole():
    if not agriculteur_connecte():
        return redirect(url_for("connexion"))
    question, reponse, erreur = "", None, None
    if request.method == "POST":
        question = request.form.get("question", "").strip()[:LONGUEUR_MAX]
        photo = None
        fichier = request.files.get("photo")
        if fichier and fichier.filename:
            donnees = encoder_photo(fichier)  # vérifie le type et la taille, comme pour les annonces
            if donnees:
                entete, contenu = donnees.split(",", 1)
                photo = (entete[len("data:"):].split(";")[0], contenu)
        if not question:
            erreur = "Écris ta question (tu peux ajouter une photo de la plante)."
        elif quota_depasse():
            erreur = "Tu as utilisé toutes tes demandes à l'assistant pour aujourd'hui. Reviens demain."
        else:
            try:
                reponse = ia.conseil_agricole(question, photo)
            except ia.IAIndisponible as exception:
                erreur = str(exception)
    return render_template("conseiller.html", question=question, reponse=reponse, erreur=erreur)
