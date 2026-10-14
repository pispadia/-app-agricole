"""Sauvegarde téléchargeable par l'admin : un fichier ZIP avec une copie JSON de chaque table.

Les photos (lourdes) ne sont incluses que sur demande, et lues par petits paquets pour ne pas
saturer la mémoire du serveur. Les pièces d'identité en attente ne sont jamais exportées.
La sauvegarde complète et automatique de chaque nuit est faite par GitHub Actions
(.github/workflows/sauvegarde.yml)."""
import json
import tempfile
import zipfile
from datetime import datetime

from flask import render_template, request, send_file

from database import get_connexion, TABLES
from core import app
from routes.premium import admin_requis

COLONNES_LOURDES = {"recoltes": "photo", "produits_fournisseur": "photo", "photos_recolte": "photo"}
EXCLUES = {"verifications": "piece"}
PAQUET = 50


def colonnes(connexion_bd, table):
    curseur = connexion_bd.execute(f"SELECT * FROM {table} WHERE 1 = 0")
    return [description[0] for description in curseur.description]


def exporter_table(connexion_bd, table, avec_photos):
    """Lignes de la table (dictionnaires), lues par paquets d'identifiants."""
    noms = [c for c in colonnes(connexion_bd, table) if c != EXCLUES.get(table)]
    if not avec_photos and table in COLONNES_LOURDES:
        noms = [c for c in noms if c != COLONNES_LOURDES[table]]
    liste = ", ".join(noms)
    if "id" not in noms:
        yield from (dict(ligne) for ligne in connexion_bd.execute(f"SELECT {liste} FROM {table}").fetchall())
        return
    dernier = 0
    while True:
        lignes = connexion_bd.execute(
            f"SELECT {liste} FROM {table} WHERE id > ? ORDER BY id LIMIT {PAQUET}", (dernier,)).fetchall()
        if not lignes:
            return
        for ligne in lignes:
            yield dict(ligne)
        dernier = lignes[-1]["id"]


@app.route("/admin/sauvegarde")
@admin_requis
def page_sauvegarde():
    return render_template("admin_sauvegarde.html")


@app.route("/admin/sauvegarde/telecharger", methods=["POST"])
@admin_requis
def telecharger_sauvegarde():
    avec_photos = request.form.get("photos") == "1"
    fichier = tempfile.SpooledTemporaryFile(max_size=20 * 1024 * 1024)
    connexion_bd = get_connexion()
    with zipfile.ZipFile(fichier, "w", zipfile.ZIP_DEFLATED) as archive:
        resume = {}
        for table in TABLES:
            nombre = 0
            with archive.open(f"{table}.jsonl", "w") as sortie:
                for ligne in exporter_table(connexion_bd, table, avec_photos):
                    sortie.write((json.dumps(ligne, ensure_ascii=False, default=str) + "\n").encode("utf-8"))
                    nombre += 1
            resume[table] = nombre
        archive.writestr("LISEZMOI.txt",
                         f"Sauvegarde App Agricole du {datetime.now():%d/%m/%Y %H:%M}\n"
                         f"Photos incluses : {'oui' if avec_photos else 'non'}\n"
                         "Un fichier par table, une ligne JSON par enregistrement.\n\n"
                         + "\n".join(f"{t} : {n} ligne(s)" for t, n in resume.items()) + "\n")
    connexion_bd.close()
    fichier.seek(0)
    return send_file(fichier, mimetype="application/zip", as_attachment=True,
                     download_name=f"sauvegarde-app-agricole-{datetime.now():%Y-%m-%d}.zip")
