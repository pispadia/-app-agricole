"""Administration : chiffres clés et gestion des comptes (suspension)."""
from datetime import date

from flask import render_template, request, redirect, url_for, session, flash
from database import get_connexion
from core import app, ROLES, adresse_admin
from routes.premium import admin_requis

LIMITE_RESULTATS = 200


@app.route("/admin/utilisateurs")
@admin_requis
def admin_utilisateurs():
    recherche = request.args.get("recherche", "").strip()
    role = request.args.get("role", "")

    requete = """SELECT utilisateurs.*,
                        (SELECT COUNT(*) FROM commandes WHERE commandes.client_id = utilisateurs.id) AS nb_achats,
                        (SELECT COUNT(*) FROM commandes JOIN recoltes ON commandes.recolte_id = recoltes.id
                         WHERE recoltes.agriculteur_id = utilisateurs.id) AS nb_ventes
                 FROM utilisateurs WHERE 1 = 1"""
    parametres = []
    if recherche:
        requete += " AND (utilisateurs.nom LIKE ? OR utilisateurs.email LIKE ? OR utilisateurs.telephone LIKE ?)"
        parametres += [f"%{recherche}%"] * 3
    if role in ROLES:
        requete += " AND utilisateurs.role = ?"
        parametres.append(role)
    requete += f" ORDER BY utilisateurs.suspendu DESC, utilisateurs.id DESC LIMIT {LIMITE_RESULTATS}"

    connexion_bd = get_connexion()
    utilisateurs = connexion_bd.execute(requete, parametres).fetchall()
    connexion_bd.close()
    return render_template("admin_utilisateurs.html", utilisateurs=utilisateurs, recherche=recherche,
                           role_choisi=role, roles=ROLES, limite=LIMITE_RESULTATS,
                           aujourdhui=date.today().isoformat())


@app.route("/admin/utilisateurs/<int:utilisateur_id>/<action>", methods=["POST"])
@admin_requis
def changer_suspension(utilisateur_id, action):
    if action not in ("suspendre", "reactiver"):
        return redirect(url_for("admin_utilisateurs"))

    connexion_bd = get_connexion()
    utilisateur = connexion_bd.execute("SELECT * FROM utilisateurs WHERE id = ?", (utilisateur_id,)).fetchone()
    if utilisateur is None:
        flash("Compte introuvable.")
    elif action == "suspendre" and (utilisateur_id == session["utilisateur_id"] or adresse_admin(utilisateur)):
        flash("Un compte administrateur ne peut pas être suspendu ici.")
    else:
        connexion_bd.execute("UPDATE utilisateurs SET suspendu = ? WHERE id = ?",
                             (1 if action == "suspendre" else 0, utilisateur_id))
        connexion_bd.commit()
        flash(f"Compte de {utilisateur['nom']} {'suspendu' if action == 'suspendre' else 'réactivé'}.")
    connexion_bd.close()
    return redirect(request.referrer if request.referrer and request.referrer.startswith(request.host_url)
                    else url_for("admin_utilisateurs"))
