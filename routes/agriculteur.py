"""Espace agriculteur : récoltes et commandes reçues."""
from flask import jsonify, render_template, request, redirect, url_for, session, flash
import push
import promo
from routes.alertes import prevenir_clients
from routes.parrainage import recompenser_parrainage
from routes.avis import NOTES_AGRICULTEURS
from routes.fiabilite_clients import FIABILITE_CLIENTS, LIVRAISONS_CLIENTS
from stock import decompter_livraison
from database import get_connexion, COLONNES_RECOLTE
from geographie import texte_lieu
from core import (app, utilisateur_courant, encoder_photo, masquer_coordonnees, date_disponibilite_valide, quantite_valide, prix_valide, utilisateur_connecte,
                  montant_valide, calculer_commission, TAUX_COMMISSION, NUMERO_PAIEMENT,
                  planning_livraison_valide, date_fr, MODES_LIVRAISON, MODES_PAIEMENT)

MAX_PHOTOS_SUPPLEMENTAIRES = 3  # en plus de la photo principale : 4 photos par annonce


def photos_supplementaires(connexion_bd, recolte_id):
    return connexion_bd.execute(
        "SELECT id FROM photos_recolte WHERE recolte_id = ? ORDER BY id", (recolte_id,)).fetchall()


def ajouter_photos_supplementaires(connexion_bd, recolte_id):
    """Enregistre les photos en plus envoyées avec le formulaire, dans la limite de 3."""
    deja = connexion_bd.execute(
        "SELECT COUNT(*) AS n FROM photos_recolte WHERE recolte_id = ?", (recolte_id,)).fetchone()["n"]
    fichiers = [f for f in request.files.getlist("photos_supplementaires") if f and f.filename]
    places = MAX_PHOTOS_SUPPLEMENTAIRES - deja
    if len(fichiers) > places:
        flash(f"4 photos maximum par annonce : seules {max(places, 0)} photo(s) en plus ont été ajoutées.")
        fichiers = fichiers[:max(places, 0)]
    for fichier in fichiers:
        photo = encoder_photo(fichier)
        if photo:
            connexion_bd.execute(
                "INSERT INTO photos_recolte (recolte_id, photo) VALUES (?, ?)", (recolte_id, photo))



@app.route("/espace-agriculteur/commandes")
def commandes_recues():
    if not utilisateur_connecte() or session["role"] != "agriculteur":
        return redirect(url_for("connexion"))

    connexion_bd = get_connexion()
    commandes = connexion_bd.execute(
        f"""SELECT commandes.*, recoltes.nom AS nom_recolte, recoltes.date_disponibilite,
                  utilisateurs.nom AS nom_client, avis_clients.note AS note_donnee_client,
                  fiabilite.note_client, fiabilite.nb_notes_client, livraisons.nb_livrees_client,
                  (SELECT COUNT(*) FROM messages_commande
                   WHERE messages_commande.commande_id = commandes.id
                     AND messages_commande.destinataire_id = ? AND messages_commande.lu = 0) AS messages_non_lus
           FROM commandes
           JOIN recoltes ON commandes.recolte_id = recoltes.id
           JOIN utilisateurs ON commandes.client_id = utilisateurs.id
           LEFT JOIN avis_clients ON avis_clients.commande_id = commandes.id
           LEFT JOIN {FIABILITE_CLIENTS} fiabilite ON fiabilite.client_id = commandes.client_id
           LEFT JOIN {LIVRAISONS_CLIENTS} livraisons ON livraisons.client_id = commandes.client_id
           WHERE recoltes.agriculteur_id = ?
           ORDER BY commandes.date_creation DESC""",
        (session["utilisateur_id"], session["utilisateur_id"])
    ).fetchall()
    connexion_bd.close()

    commission_due = sum((c["commission"] or 0) for c in commandes
                         if c["statut"] == "livree" and not c["commission_payee"])
    return render_template("commandes_recues.html", nom=session["nom"], commandes=commandes,
                           transitions=TRANSITIONS_COMMANDE, commission_due=commission_due,
                           taux_commission=TAUX_COMMISSION, numero_paiement=NUMERO_PAIEMENT,
                           modes_livraison=MODES_LIVRAISON, modes_paiement=MODES_PAIEMENT)


# Changements de statut autorisés pour l'agriculteur : statut actuel -> statuts possibles
TRANSITIONS_COMMANDE = {
    "en_attente": ("confirmee", "annulee"),
    "confirmee": ("livree", "annulee"),
}


MESSAGES_STATUT = {"confirmee": "confirmée", "livree": "livrée", "annulee": "annulée"}


def alerter_client(commande, statut, precision=""):
    push.alerter(commande["client_id"], commande["telephone_client"],
                 f"App Agricole : ta commande de {commande['nom_recolte']} a été {MESSAGES_STATUT[statut]} "
                 f"par {session['nom']}.{precision}", url_for("mes_commandes"))


@app.route("/espace-agriculteur/commandes/<int:commande_id>/statut", methods=["POST"])
def changer_statut_commande(commande_id):
    if not utilisateur_connecte() or session["role"] != "agriculteur":
        return redirect(url_for("connexion"))

    nouveau_statut = request.form.get("statut", "")
    connexion_bd = get_connexion()
    # Seulement les commandes portant sur une récolte de cet agriculteur
    commande = connexion_bd.execute(
        """SELECT commandes.statut, commandes.client_id, commandes.negociation, commandes.mode_livraison, commandes.mode_paiement, commandes.paye_en_ligne,
                  recoltes.nom AS nom_recolte, utilisateurs.telephone AS telephone_client
           FROM commandes
           JOIN recoltes ON commandes.recolte_id = recoltes.id
           JOIN utilisateurs ON commandes.client_id = utilisateurs.id
           WHERE commandes.id = ? AND recoltes.agriculteur_id = ?""",
        (commande_id, session["utilisateur_id"])
    ).fetchone()

    if not (commande and nouveau_statut in TRANSITIONS_COMMANDE.get(commande["statut"], ())):
        flash("Ce changement de statut n'est pas possible.")
    elif nouveau_statut == "livree" and commande["paye_en_ligne"]:
        # Déjà payée en ligne : montant et commission sont connus, l'admin reversera la somme due
        connexion_bd.execute("UPDATE commandes SET statut = 'livree', lu_client = 0 WHERE id = ?", (commande_id,))
        info_stock = decompter_livraison(connexion_bd, commande_id)
        connexion_bd.commit()
        recompenser_parrainage(connexion_bd, commande_id)
        alerter_client(commande, "livree")
        flash("Commande livrée. La plateforme va te reverser le montant de la vente (commission déduite).")
        flash(info_stock)
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
            info_stock = decompter_livraison(connexion_bd, commande_id)
            connexion_bd.commit()
            alerter_client(commande, "livree")
            flash(f"Commande livrée. Commission de la plateforme : {commission} FCFA.")
            flash(info_stock)
    elif nouveau_statut == "confirmee" and commande["negociation"] in ("proposee", "contre_offre"):
        flash("Réponds d'abord à l'offre de prix du client (accepter ou contre-offre).")
    elif nouveau_statut == "confirmee":
        # À la confirmation, l'agriculteur peut fixer la date et les frais de livraison
        try:
            date_prevue, frais = planning_livraison_valide(request.form)
            # Paiement en ligne : l'agriculteur fixe le prix, que le client paiera via Wave
            montant = montant_a_payer = commission = None
            if commande["mode_paiement"] == "wave":
                montant = montant_valide(request.form.get("montant", ""))
                commission = calculer_commission(montant)
                montant_a_payer = montant + (frais or 0)
        except ValueError as erreur:
            flash(str(erreur))
        else:
            connexion_bd.execute(
                """UPDATE commandes SET statut = 'confirmee', lu_client = 0,
                          date_livraison_prevue = ?, frais_livraison = ?,
                          montant = ?, commission = ?, montant_a_payer = ? WHERE id = ?""",
                (date_prevue, frais, montant, commission, montant_a_payer, commande_id)
            )
            connexion_bd.commit()
            precision = ""
            if date_prevue:
                verbe = "Livraison" if commande["mode_livraison"] == "livraison" else "Retrait"
                precision = f" {verbe} prévu(e) le {date_fr(date_prevue)}."
            if frais:
                precision += f" Frais de livraison : {frais} FCFA."
            if montant_a_payer:
                precision += f" A payer avec Wave : {montant_a_payer} FCFA."
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
        f"SELECT {COLONNES_RECOLTE} FROM recoltes WHERE agriculteur_id = ? ORDER BY date_creation DESC",
        (session["utilisateur_id"],)
    ).fetchall()
    verification = connexion_bd.execute(
        "SELECT verification FROM utilisateurs WHERE id = ?", (session["utilisateur_id"],)).fetchone()["verification"]
    chiffres = connexion_bd.execute(
        """SELECT SUM(CASE WHEN commandes.statut = 'en_attente' THEN 1 ELSE 0 END) AS en_attente,
                  COALESCE(SUM(CASE WHEN commandes.statut = 'livree' THEN commandes.montant END), 0) AS ventes
           FROM commandes JOIN recoltes ON commandes.recolte_id = recoltes.id
           WHERE recoltes.agriculteur_id = ?""", (session["utilisateur_id"],)
    ).fetchone()
    notes = connexion_bd.execute(
        f"SELECT note_moyenne, nb_avis FROM {NOTES_AGRICULTEURS} notes WHERE agriculteur_id = ?",
        (session["utilisateur_id"],)
    ).fetchone()
    connexion_bd.close()

    return render_template(
        "espace_agriculteur.html", nom=session["nom"], recoltes=recoltes, verification=verification,
        en_ligne=sum(1 for r in recoltes if r["statut"] == "disponible" and not r["masquee"]),
        en_attente=chiffres["en_attente"] or 0, ventes=chiffres["ventes"], notes=notes,
        pourcentages_promo=promo.POURCENTAGES, durees_promo=promo.DUREES_JOURS,
    )


@app.route("/espace-agriculteur/nouvelle-recolte", methods=["GET", "POST"])
def nouvelle_recolte():
    # Annonce préparée hors connexion et envoyée plus tard par le téléphone (static/hors_ligne.js) :
    # on répond en JSON pour que le script sache si elle est publiée
    hors_ligne = request.headers.get("X-Hors-Ligne") == "1"
    if not utilisateur_connecte() or session["role"] != "agriculteur":
        return (jsonify({"erreur": "Connecte-toi pour publier."}), 401) if hors_ligne else redirect(url_for("connexion"))

    if request.method == "POST":
        nom = request.form["nom"]
        try:
            quantite = quantite_valide(request.form["quantite"])
            prix = prix_valide(request.form["prix"])
            prix_gros = request.form.get("prix_gros", "").strip() or None
            if prix_gros:
                prix_gros = prix_valide(prix_gros)
            date_disponibilite = date_disponibilite_valide(request.form.get("date_disponibilite"))
        except ValueError as erreur:
            if hors_ligne:
                return jsonify({"erreur": str(erreur)}), 400
            flash(str(erreur))
            return render_template("nouvelle_recolte.html", saisie=request.form)
        quantite_gros_min = request.form.get("quantite_gros_min", "").strip() or None
        localite = request.form["localite"]
        # Pas de numéro ni d'e-mail dans l'annonce : les échanges passent par la plateforme
        description = masquer_coordonnees(request.form.get("description", ""))

        fichier = request.files.get("photo")
        nom_photo = encoder_photo(fichier)

        connexion_bd = get_connexion()
        recolte_id = connexion_bd.execute(
            """INSERT INTO recoltes
               (agriculteur_id, nom, quantite, prix, prix_gros, quantite_gros_min,
                date_disponibilite, localite, description, photo)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id""",
            (session["utilisateur_id"], nom, quantite, prix, prix_gros, quantite_gros_min,
             date_disponibilite, localite, description, nom_photo)
        ).fetchone()["id"]
        ajouter_photos_supplementaires(connexion_bd, recolte_id)
        connexion_bd.commit()
        prevenir_clients(connexion_bd, recolte_id, nom, localite, prix, session["utilisateur_id"])
        connexion_bd.close()

        if hors_ligne:
            return jsonify({"ok": True, "id": recolte_id})
        flash("Récolte publiée avec succès.")
        return redirect(url_for("espace_agriculteur"))

    # La localité est préremplie avec l'adresse donnée à l'inscription
    return render_template("nouvelle_recolte.html", saisie={"localite": texte_lieu(utilisateur_courant())})


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
            date_disponibilite = date_disponibilite_valide(request.form.get("date_disponibilite"))
        except ValueError as erreur:
            flash(str(erreur))
            photos = photos_supplementaires(connexion_bd, recolte_id)
            connexion_bd.close()
            return render_template("modifier_recolte.html", recolte={**dict(recolte), **request.form.to_dict()},
                                   photos=photos)
        quantite_gros_min = request.form.get("quantite_gros_min", "").strip() or None
        localite = request.form["localite"]
        # Pas de numéro ni d'e-mail dans l'annonce : les échanges passent par la plateforme
        description = masquer_coordonnees(request.form.get("description", ""))
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
        for photo_id in request.form.getlist("supprimer_photo"):
            if photo_id.isdigit():
                connexion_bd.execute("DELETE FROM photos_recolte WHERE id = ? AND recolte_id = ?",
                                     (int(photo_id), recolte_id))
        ajouter_photos_supplementaires(connexion_bd, recolte_id)
        connexion_bd.commit()
        connexion_bd.close()

        flash("Récolte mise à jour.")
        return redirect(url_for("espace_agriculteur"))

    photos = photos_supplementaires(connexion_bd, recolte_id)
    connexion_bd.close()
    return render_template("modifier_recolte.html", recolte=recolte, photos=photos)


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
