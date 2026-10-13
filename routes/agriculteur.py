"""Espace agriculteur : récoltes et commandes reçues."""
from flask import render_template, request, redirect, url_for, session, flash
import sms
from database import get_connexion
from core import (app, encoder_photo, quantite_valide, prix_valide, utilisateur_connecte,
                  montant_valide, calculer_commission, TAUX_COMMISSION, NUMERO_PAIEMENT,
                  planning_livraison_valide, date_fr, MODES_LIVRAISON)


@app.route("/espace-agriculteur/commandes")
def commandes_recues():
    if not utilisateur_connecte() or session["role"] != "agriculteur":
        return redirect(url_for("connexion"))

    connexion_bd = get_connexion()
    commandes = connexion_bd.execute(
        """SELECT commandes.*, recoltes.nom AS nom_recolte,
                  utilisateurs.nom AS nom_client, utilisateurs.email AS email_client,
                  utilisateurs.telephone AS telephone_client
           FROM commandes
           JOIN recoltes ON commandes.recolte_id = recoltes.id
           JOIN utilisateurs ON commandes.client_id = utilisateurs.id
           WHERE recoltes.agriculteur_id = ?
           ORDER BY commandes.date_creation DESC""",
        (session["utilisateur_id"],)
    ).fetchall()
    connexion_bd.close()

    commission_due = sum((c["commission"] or 0) for c in commandes
                         if c["statut"] == "livree" and not c["commission_payee"])
    return render_template("commandes_recues.html", nom=session["nom"], commandes=commandes,
                           transitions=TRANSITIONS_COMMANDE, commission_due=commission_due,
                           taux_commission=TAUX_COMMISSION, numero_paiement=NUMERO_PAIEMENT,
                           modes_livraison=MODES_LIVRAISON)


# Changements de statut autorisés pour l'agriculteur : statut actuel -> statuts possibles
TRANSITIONS_COMMANDE = {
    "en_attente": ("confirmee", "annulee"),
    "confirmee": ("livree", "annulee"),
}


MESSAGES_STATUT = {"confirmee": "confirmée", "livree": "livrée", "annulee": "annulée"}


def alerter_client(commande, statut, precision=""):
    sms.alerter(commande["telephone_client"],
                f"App Agricole : ta commande de {commande['nom_recolte']} a été {MESSAGES_STATUT[statut]} "
                f"par {session['nom']}.{precision}")


@app.route("/espace-agriculteur/commandes/<int:commande_id>/statut", methods=["POST"])
def changer_statut_commande(commande_id):
    if not utilisateur_connecte() or session["role"] != "agriculteur":
        return redirect(url_for("connexion"))

    nouveau_statut = request.form.get("statut", "")
    connexion_bd = get_connexion()
    # Seulement les commandes portant sur une récolte de cet agriculteur
    commande = connexion_bd.execute(
        """SELECT commandes.statut, commandes.mode_livraison, recoltes.nom AS nom_recolte, utilisateurs.telephone AS telephone_client
           FROM commandes
           JOIN recoltes ON commandes.recolte_id = recoltes.id
           JOIN utilisateurs ON commandes.client_id = utilisateurs.id
           WHERE commandes.id = ? AND recoltes.agriculteur_id = ?""",
        (commande_id, session["utilisateur_id"])
    ).fetchone()

    if not (commande and nouveau_statut in TRANSITIONS_COMMANDE.get(commande["statut"], ())):
        flash("Ce changement de statut n'est pas possible.")
    elif nouveau_statut == "livree":
        # À la livraison, l'agriculteur indique le montant encaissé : la commission
        # de la plateforme est calculée dessus
        try:
            montant = montant_valide(request.form.get("montant", ""))
        except ValueError as erreur:
            flash(str(erreur))
        else:
            commission = calculer_commission(montant)
            connexion_bd.execute(
                """UPDATE commandes SET statut = 'livree', lu_client = 0, montant = ?, commission = ?
                   WHERE id = ?""", (montant, commission, commande_id)
            )
            connexion_bd.commit()
            alerter_client(commande, "livree")
            flash(f"Commande livrée. Commission de la plateforme : {commission} FCFA.")
    elif nouveau_statut == "confirmee":
        # À la confirmation, l'agriculteur peut fixer la date et les frais de livraison
        try:
            date_prevue, frais = planning_livraison_valide(request.form)
        except ValueError as erreur:
            flash(str(erreur))
        else:
            connexion_bd.execute(
                """UPDATE commandes SET statut = 'confirmee', lu_client = 0,
                          date_livraison_prevue = ?, frais_livraison = ? WHERE id = ?""",
                (date_prevue, frais, commande_id)
            )
            connexion_bd.commit()
            precision = ""
            if date_prevue:
                verbe = "Livraison" if commande["mode_livraison"] == "livraison" else "Retrait"
                precision = f" {verbe} prévu(e) le {date_fr(date_prevue)}."
            if frais:
                precision += f" Frais de livraison : {frais} FCFA."
            alerter_client(commande, "confirmee", precision)
            flash("Commande confirmée.")
    else:
        connexion_bd.execute(
            "UPDATE commandes SET statut = ?, lu_client = 0 WHERE id = ?", (nouveau_statut, commande_id)
        )
        connexion_bd.commit()
        alerter_client(commande, nouveau_statut)
        flash("Statut de la commande mis à jour.")

    connexion_bd.close()
    return redirect(url_for("commandes_recues"))


@app.route("/espace-agriculteur")
def espace_agriculteur():
    if not utilisateur_connecte() or session["role"] != "agriculteur":
        return redirect(url_for("connexion"))

    connexion_bd = get_connexion()
    recoltes = connexion_bd.execute(
        "SELECT * FROM recoltes WHERE agriculteur_id = ? ORDER BY date_creation DESC",
        (session["utilisateur_id"],)
    ).fetchall()
    connexion_bd.close()

    return render_template("espace_agriculteur.html", nom=session["nom"], recoltes=recoltes)


@app.route("/espace-agriculteur/nouvelle-recolte", methods=["GET", "POST"])
def nouvelle_recolte():
    if not utilisateur_connecte() or session["role"] != "agriculteur":
        return redirect(url_for("connexion"))

    if request.method == "POST":
        nom = request.form["nom"]
        try:
            quantite = quantite_valide(request.form["quantite"])
            prix = prix_valide(request.form["prix"])
            prix_gros = request.form.get("prix_gros", "").strip() or None
            if prix_gros:
                prix_gros = prix_valide(prix_gros)
        except ValueError as erreur:
            flash(str(erreur))
            return render_template("nouvelle_recolte.html", saisie=request.form)
        quantite_gros_min = request.form.get("quantite_gros_min", "").strip() or None
        date_disponibilite = request.form["date_disponibilite"]
        localite = request.form["localite"]
        description = request.form.get("description", "")

        fichier = request.files.get("photo")
        nom_photo = encoder_photo(fichier)

        connexion_bd = get_connexion()
        connexion_bd.execute(
            """INSERT INTO recoltes
               (agriculteur_id, nom, quantite, prix, prix_gros, quantite_gros_min,
                date_disponibilite, localite, description, photo)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (session["utilisateur_id"], nom, quantite, prix, prix_gros, quantite_gros_min,
             date_disponibilite, localite, description, nom_photo)
        )
        connexion_bd.commit()
        connexion_bd.close()

        flash("Récolte publiée avec succès.")
        return redirect(url_for("espace_agriculteur"))

    return render_template("nouvelle_recolte.html")


@app.route("/espace-agriculteur/modifier-recolte/<int:recolte_id>", methods=["GET", "POST"])
def modifier_recolte(recolte_id):
    if not utilisateur_connecte() or session["role"] != "agriculteur":
        return redirect(url_for("connexion"))

    connexion_bd = get_connexion()
    recolte = connexion_bd.execute(
        "SELECT * FROM recoltes WHERE id = ? AND agriculteur_id = ?",
        (recolte_id, session["utilisateur_id"])
    ).fetchone()

    if recolte is None:
        connexion_bd.close()
        flash("Récolte introuvable.")
        return redirect(url_for("espace_agriculteur"))

    if request.method == "POST":
        nom = request.form["nom"]
        try:
            quantite = quantite_valide(request.form["quantite"])
            prix = prix_valide(request.form["prix"])
            prix_gros = request.form.get("prix_gros", "").strip() or None
            if prix_gros:
                prix_gros = prix_valide(prix_gros)
        except ValueError as erreur:
            flash(str(erreur))
            connexion_bd.close()
            return render_template("modifier_recolte.html", recolte={**dict(recolte), **request.form.to_dict()})
        quantite_gros_min = request.form.get("quantite_gros_min", "").strip() or None
        date_disponibilite = request.form["date_disponibilite"]
        localite = request.form["localite"]
        description = request.form.get("description", "")
        statut = request.form.get("statut", "disponible")

        fichier = request.files.get("photo")
        nom_photo = encoder_photo(fichier) or recolte["photo"]

        connexion_bd.execute(
            """UPDATE recoltes SET
               nom = ?, quantite = ?, prix = ?, prix_gros = ?, quantite_gros_min = ?,
               date_disponibilite = ?, localite = ?, description = ?, photo = ?, statut = ?
               WHERE id = ? AND agriculteur_id = ?""",
            (nom, quantite, prix, prix_gros, quantite_gros_min, date_disponibilite,
             localite, description, nom_photo, statut, recolte_id, session["utilisateur_id"])
        )
        connexion_bd.commit()
        connexion_bd.close()

        flash("Récolte mise à jour.")
        return redirect(url_for("espace_agriculteur"))

    connexion_bd.close()
    return render_template("modifier_recolte.html", recolte=recolte)


@app.route("/espace-agriculteur/basculer-statut/<int:recolte_id>", methods=["POST"])
def basculer_statut(recolte_id):
    if not utilisateur_connecte() or session["role"] != "agriculteur":
        return redirect(url_for("connexion"))

    connexion_bd = get_connexion()
    recolte = connexion_bd.execute(
        "SELECT statut FROM recoltes WHERE id = ? AND agriculteur_id = ?",
        (recolte_id, session["utilisateur_id"])
    ).fetchone()

    if recolte:
        nouveau_statut = "epuise" if recolte["statut"] == "disponible" else "disponible"
        connexion_bd.execute(
            "UPDATE recoltes SET statut = ? WHERE id = ? AND agriculteur_id = ?",
            (nouveau_statut, recolte_id, session["utilisateur_id"])
        )
        connexion_bd.commit()

    connexion_bd.close()
    return redirect(url_for("espace_agriculteur"))
