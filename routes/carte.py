"""Carte des producteurs : les annonces disponibles placées sur une carte du Sénégal."""
from flask import render_template, url_for

from database import get_connexion
from core import app
from localites import coordonnees
from routes.client import rechercher_recoltes


@app.route("/carte")
def carte_producteurs():
    connexion_bd = get_connexion()
    recoltes = rechercher_recoltes(connexion_bd)
    connexion_bd.close()

    points, non_placees = {}, []
    for recolte in recoltes:
        position = coordonnees(recolte["localite"])
        if position is None:
            non_placees.append(recolte)
            continue
        point = points.setdefault(position, {"lat": position[0], "lon": position[1], "annonces": []})
        point["annonces"].append({
            "nom": recolte["nom"], "prix": recolte["prix"], "localite": recolte["localite"],
            "quantite": recolte["quantite"], "vendeur": recolte["nom_agriculteur"],
            "url": url_for("voir_annonce", recolte_id=recolte["id"]),
            "photo": url_for("photo_annonce", recolte_id=recolte["id"]) if recolte["a_photo"] else None,
        })
    return render_template("carte.html", points=list(points.values()), non_placees=non_placees,
                           total=len(recoltes))
