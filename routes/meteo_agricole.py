"""Météo agricole de l'agriculteur : 7 jours de prévisions et conseils pour sa localité."""
from flask import redirect, render_template, request, session, url_for

import meteo
from database import get_connexion
from core import app, utilisateur_connecte
from localites import coordonnees


def localite_agriculteur(agriculteur_id):
    """Localité choisie (?lieu=...), sinon celle de sa dernière annonce."""
    lieu = request.args.get("lieu", "").strip()
    if lieu:
        return lieu
    connexion_bd = get_connexion()
    ligne = connexion_bd.execute(
        "SELECT localite FROM recoltes WHERE agriculteur_id = ? ORDER BY date_creation DESC, id DESC LIMIT 1",
        (agriculteur_id,)).fetchone()
    connexion_bd.close()
    return ligne["localite"] if ligne else ""


def donnees_meteo():
    lieu = localite_agriculteur(session["utilisateur_id"])
    position = coordonnees(lieu)
    jours = meteo.previsions(*position) if position else None
    return {"lieu": lieu, "lieu_connu": position is not None, "jours": jours, "conseils": meteo.conseils(jours)}


@app.route("/espace-agriculteur/meteo")
def meteo_agriculteur():
    if not utilisateur_connecte() or session["role"] != "agriculteur":
        return redirect(url_for("connexion"))
    return render_template("meteo.html", **donnees_meteo())


@app.route("/espace-agriculteur/meteo/resume")
def resume_meteo():
    """Petit bandeau météo chargé après coup par l'espace agriculteur (page jamais ralentie)."""
    if not utilisateur_connecte() or session["role"] != "agriculteur":
        return "", 204
    donnees = donnees_meteo()
    if not donnees["jours"]:
        return "", 204
    return render_template("_resume_meteo.html", **donnees)
