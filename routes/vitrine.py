"""Vitrine publique : page d'accueil, catalogue sans compte, référencement (robots.txt, sitemap.xml)."""
from datetime import date

from flask import render_template, Response, url_for
from database import get_connexion
from core import app
from routes.client import donnees_catalogue, rechercher_recoltes

NOMBRE_ANNONCES_ACCUEIL = 6


def page_accueil():
    """Accueil d'un visiteur : dernières récoltes et chiffres clés (appelée par la route « / »)."""
    connexion_bd = get_connexion()
    recoltes = rechercher_recoltes(connexion_bd, limite=NOMBRE_ANNONCES_ACCUEIL)
    chiffres = {
        "agriculteurs": connexion_bd.execute(
            "SELECT COUNT(*) AS n FROM utilisateurs WHERE role = 'agriculteur' AND suspendu = 0").fetchone()["n"],
        "annonces": connexion_bd.execute(
            "SELECT COUNT(*) AS n FROM recoltes WHERE statut = 'disponible'").fetchone()["n"],
        "livraisons": connexion_bd.execute(
            "SELECT COUNT(*) AS n FROM commandes WHERE statut = 'livree'").fetchone()["n"],
    }
    connexion_bd.close()
    return render_template("accueil.html", recoltes=recoltes, chiffres=chiffres,
                           aujourdhui=date.today().isoformat())


@app.route("/catalogue")
def catalogue_public():
    connexion_bd = get_connexion()
    donnees = donnees_catalogue(connexion_bd)
    connexion_bd.close()
    return render_template("catalogue_public.html", **donnees)


@app.route("/robots.txt")
def robots():
    lignes = ["User-agent: *", "Allow: /$", "Allow: /catalogue", "Allow: /annonce/", "Allow: /prix-du-marche",
              "Disallow: /", f"Sitemap: {url_for('plan_du_site', _external=True)}"]
    return Response("\n".join(lignes) + "\n", mimetype="text/plain")


@app.route("/sitemap.xml")
def plan_du_site():
    connexion_bd = get_connexion()
    annonces = connexion_bd.execute(
        """SELECT recoltes.id FROM recoltes JOIN utilisateurs ON recoltes.agriculteur_id = utilisateurs.id
           WHERE recoltes.statut = 'disponible' AND recoltes.masquee = 0 AND utilisateurs.suspendu = 0 ORDER BY recoltes.id DESC LIMIT 5000"""
    ).fetchall()
    connexion_bd.close()
    adresses = [url_for("accueil", _external=True), url_for("catalogue_public", _external=True),
                url_for("prix_marche", _external=True)]
    adresses += [url_for("voir_annonce", recolte_id=a["id"], _external=True) for a in annonces]
    xml = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    xml += [f"  <url><loc>{adresse}</loc></url>" for adresse in adresses]
    xml.append("</urlset>")
    return Response("\n".join(xml), mimetype="application/xml")
