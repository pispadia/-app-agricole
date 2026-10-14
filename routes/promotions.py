"""Mettre une annonce en promotion (ou arrêter la promotion) depuis l'espace agriculteur."""
from flask import request, redirect, url_for, session, flash

import promo
from database import get_connexion
from core import app, utilisateur_connecte, date_fr


@app.route("/espace-agriculteur/recolte/<int:recolte_id>/promo", methods=["POST"])
def promotion_recolte(recolte_id):
    if not utilisateur_connecte() or session["role"] != "agriculteur":
        return redirect(url_for("connexion"))
    connexion_bd = get_connexion()
    recolte = connexion_bd.execute("SELECT prix FROM recoltes WHERE id = ? AND agriculteur_id = ?",
                                   (recolte_id, session["utilisateur_id"])).fetchone()
    if recolte is None:
        connexion_bd.close()
        flash("Récolte introuvable.")
        return redirect(url_for("espace_agriculteur"))

    if request.form.get("action") == "arreter":
        connexion_bd.execute("UPDATE recoltes SET promo_pourcent = NULL, promo_jusqu_au = NULL WHERE id = ?",
                             (recolte_id,))
        flash("Promotion arrêtée : le prix normal s'applique.")
    else:
        pourcent = request.form.get("pourcent", type=int)
        duree = request.form.get("duree", type=int)
        if pourcent not in promo.POURCENTAGES or duree not in promo.DUREES_JOURS:
            connexion_bd.close()
            flash("Choisis une réduction et une durée.")
            return redirect(url_for("espace_agriculteur"))
        fin = promo.fin_promo(duree)
        connexion_bd.execute("UPDATE recoltes SET promo_pourcent = ?, promo_jusqu_au = ? WHERE id = ?",
                             (pourcent, fin, recolte_id))
        flash(f"Promotion −{pourcent} % jusqu'au {date_fr(fin)} : nouveau prix "
              f"{promo.prix_reduit(recolte['prix'], pourcent)}.")
    connexion_bd.commit()
    connexion_bd.close()
    return redirect(url_for("espace_agriculteur"))
