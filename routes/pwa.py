"""Installation sur téléphone (application web progressive) : manifeste, service worker, page hors ligne."""
from flask import jsonify, render_template, send_from_directory, url_for
from core import app


@app.route("/manifest.webmanifest")
def manifeste():
    reponse = jsonify({
        "name": "App Agricole",
        "short_name": "App Agricole",
        "description": "Vendre et acheter des récoltes au Sénégal, trouver semences et financement.",
        "lang": "fr",
        "start_url": url_for("accueil"),
        "scope": "/",
        "display": "standalone",
        "background_color": "#f4f7f2",
        "theme_color": "#2e7d32",
        "icons": [
            {"src": url_for("static", filename=f"icones/icone-{taille}.png"),
             "sizes": f"{taille}x{taille}", "type": "image/png", "purpose": "any maskable"}
            for taille in (192, 512)
        ],
    })
    reponse.mimetype = "application/manifest+json"
    return reponse


@app.route("/sw.js")
def service_worker():
    # Servi depuis la racine pour pouvoir gérer toutes les pages du site
    reponse = send_from_directory(app.static_folder, "sw.js", mimetype="application/javascript")
    reponse.headers["Cache-Control"] = "no-cache"
    return reponse


@app.route("/hors-ligne")
def hors_ligne():
    return render_template("hors_ligne.html")
