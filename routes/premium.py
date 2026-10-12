"""Abonnement Premium et espace administrateur (suivi des revenus)."""
from datetime import date, timedelta
from functools import wraps

from flask import render_template, request, redirect, url_for, session, flash
from database import get_connexion
from core import (app, utilisateur_connecte, date_fin_premium, est_admin,
                  PRIX_PREMIUM_MENSUEL, DUREE_PREMIUM_JOURS, NUMERO_PAIEMENT, TAUX_COMMISSION)


@app.route("/premium", methods=["GET", "POST"])
def premium():
    if not utilisateur_connecte():
        return redirect(url_for("connexion"))

    connexion_bd = get_connexion()
    if request.method == "POST":
        reference = " ".join(request.form.get("reference", "").split())
        if not reference:
            flash("Indique la référence de ton paiement (reçue par SMS).")
        else:
            connexion_bd.execute(
                "INSERT INTO paiements_premium (utilisateur_id, reference, montant) VALUES (?, ?, ?)",
                (session["utilisateur_id"], reference[:100], PRIX_PREMIUM_MENSUEL)
            )
            connexion_bd.commit()
            flash("Paiement déclaré. Ton abonnement sera activé dès sa vérification.")
        connexion_bd.close()
        return redirect(url_for("premium"))

    paiements = connexion_bd.execute(
        "SELECT * FROM paiements_premium WHERE utilisateur_id = ? ORDER BY date_creation DESC",
        (session["utilisateur_id"],)
    ).fetchall()
    connexion_bd.close()

    return render_template(
        "premium.html", paiements=paiements, prix=PRIX_PREMIUM_MENSUEL,
        duree=DUREE_PREMIUM_JOURS, numero_paiement=NUMERO_PAIEMENT,
    )


def admin_requis(vue):
    @wraps(vue)
    def vue_protegee(*args, **kwargs):
        if not est_admin():
            return redirect(url_for("accueil"))
        return vue(*args, **kwargs)
    return vue_protegee


@app.route("/admin")
@admin_requis
def admin():
    connexion_bd = get_connexion()
    paiements_en_attente = connexion_bd.execute(
        """SELECT paiements_premium.*, utilisateurs.nom, utilisateurs.email, utilisateurs.role
           FROM paiements_premium JOIN utilisateurs ON paiements_premium.utilisateur_id = utilisateurs.id
           WHERE paiements_premium.statut = 'en_attente'
           ORDER BY paiements_premium.date_creation"""
    ).fetchall()
    commissions_dues = connexion_bd.execute(
        """SELECT commandes.*, recoltes.nom AS nom_recolte, utilisateurs.nom AS nom_agriculteur,
                  utilisateurs.telephone AS telephone_agriculteur
           FROM commandes
           JOIN recoltes ON commandes.recolte_id = recoltes.id
           JOIN utilisateurs ON recoltes.agriculteur_id = utilisateurs.id
           WHERE commandes.statut = 'livree' AND commandes.commission_payee = 0
           ORDER BY utilisateurs.nom, commandes.date_creation"""
    ).fetchall()
    totaux = {
        "ventes": connexion_bd.execute(
            "SELECT COALESCE(SUM(montant), 0) AS n FROM commandes WHERE statut = 'livree'").fetchone()["n"],
        "commissions_encaissees": connexion_bd.execute(
            "SELECT COALESCE(SUM(commission), 0) AS n FROM commandes WHERE statut = 'livree' AND commission_payee = 1"
        ).fetchone()["n"],
        "commissions_dues": sum(c["commission"] or 0 for c in commissions_dues),
        "premium_encaisse": connexion_bd.execute(
            "SELECT COALESCE(SUM(montant), 0) AS n FROM paiements_premium WHERE statut = 'valide'").fetchone()["n"],
        "abonnes": connexion_bd.execute(
            "SELECT COUNT(*) AS n FROM utilisateurs WHERE premium_jusqu_au >= ?",
            (date.today().isoformat(),)).fetchone()["n"],
    }
    connexion_bd.close()
    return render_template("admin.html", paiements=paiements_en_attente, commissions=commissions_dues,
                           totaux=totaux, taux_commission=TAUX_COMMISSION)


@app.route("/admin/paiements/<int:paiement_id>/<decision>", methods=["POST"])
@admin_requis
def traiter_paiement(paiement_id, decision):
    connexion_bd = get_connexion()
    paiement = connexion_bd.execute(
        """SELECT paiements_premium.*, utilisateurs.premium_jusqu_au
           FROM paiements_premium JOIN utilisateurs ON paiements_premium.utilisateur_id = utilisateurs.id
           WHERE paiements_premium.id = ? AND paiements_premium.statut = 'en_attente'""", (paiement_id,)
    ).fetchone()

    if paiement and decision == "valider":
        # Prolonge l'abonnement à partir de sa date de fin s'il est encore actif, sinon d'aujourd'hui
        debut = date_fin_premium(paiement) or date.today()
        fin = debut + timedelta(days=DUREE_PREMIUM_JOURS)
        connexion_bd.execute("UPDATE utilisateurs SET premium_jusqu_au = ? WHERE id = ?",
                             (fin.isoformat(), paiement["utilisateur_id"]))
        connexion_bd.execute("UPDATE paiements_premium SET statut = 'valide' WHERE id = ?", (paiement_id,))
        connexion_bd.commit()
        flash(f"Paiement validé : Premium jusqu'au {fin.strftime('%d/%m/%Y')}.")
    elif paiement and decision == "refuser":
        connexion_bd.execute("UPDATE paiements_premium SET statut = 'refuse' WHERE id = ?", (paiement_id,))
        connexion_bd.commit()
        flash("Paiement refusé.")
    else:
        flash("Paiement introuvable ou déjà traité.")

    connexion_bd.close()
    return redirect(url_for("admin"))


@app.route("/admin/commissions/<int:commande_id>/reglee", methods=["POST"])
@admin_requis
def commission_reglee(commande_id):
    connexion_bd = get_connexion()
    connexion_bd.execute(
        "UPDATE commandes SET commission_payee = 1 WHERE id = ? AND statut = 'livree'", (commande_id,)
    )
    connexion_bd.commit()
    connexion_bd.close()
    flash("Commission marquée comme réglée.")
    return redirect(url_for("admin"))
