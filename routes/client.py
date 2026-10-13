"""Espace client : catalogue, panier et commandes."""
from datetime import date

from flask import render_template, request, redirect, url_for, session, flash
import sms
from database import get_connexion
from core import app, quantite_valide, utilisateur_connecte, livraison_valide, MODES_LIVRAISON
from routes.avis import NOTES_AGRICULTEURS


@app.route("/espace-client")
def espace_client():
    if not utilisateur_connecte() or session["role"] != "client":
        return redirect(url_for("connexion"))

    recherche = request.args.get("recherche", "").strip()
    localite = request.args.get("localite", "").strip()
    tri = request.args.get("tri", "recent")

    requete = """
        SELECT recoltes.*, utilisateurs.nom AS nom_agriculteur,
               utilisateurs.telephone AS telephone_agriculteur,
               utilisateurs.premium_jusqu_au AS premium_agriculteur,
               notes.note_moyenne, notes.nb_avis
        FROM recoltes
        JOIN utilisateurs ON recoltes.agriculteur_id = utilisateurs.id
        LEFT JOIN """ + NOTES_AGRICULTEURS + """ notes ON notes.agriculteur_id = recoltes.agriculteur_id
        WHERE recoltes.statut = 'disponible'
    """
    parametres = []

    if recherche:
        requete += " AND (recoltes.nom LIKE ? OR recoltes.description LIKE ?)"
        parametres.append(f"%{recherche}%")
        parametres.append(f"%{recherche}%")

    if localite:
        requete += " AND recoltes.localite LIKE ?"
        parametres.append(f"%{localite}%")

    ordres = {
        "recent": "recoltes.date_creation DESC",
        "nom": "recoltes.nom ASC",
        "localite": "recoltes.localite ASC",
        "note": "COALESCE(notes.note_moyenne, 0) DESC, recoltes.date_creation DESC",
    }
    # Les annonces des membres Premium passent en premier
    aujourdhui = date.today().isoformat()
    requete += (" ORDER BY CASE WHEN utilisateurs.premium_jusqu_au >= ? THEN 0 ELSE 1 END, "
                + ordres.get(tri, ordres["recent"]))
    parametres.append(aujourdhui)

    connexion_bd = get_connexion()
    recoltes = connexion_bd.execute(requete, parametres).fetchall()
    localites = connexion_bd.execute(
        "SELECT DISTINCT localite FROM recoltes WHERE statut = 'disponible' ORDER BY localite"
    ).fetchall()
    connexion_bd.close()

    return render_template(
        "espace_client.html", nom=session["nom"], recoltes=recoltes,
        localites=localites, recherche=recherche, localite_choisie=localite, tri_choisi=tri,
        taille_panier=len(session.get("panier", [])), aujourdhui=aujourdhui
    )


def get_recolte_avec_agriculteur(connexion_bd, recolte_id):
    return connexion_bd.execute(
        """SELECT recoltes.*, utilisateurs.nom AS nom_agriculteur,
                  utilisateurs.telephone AS telephone_agriculteur
           FROM recoltes JOIN utilisateurs ON recoltes.agriculteur_id = utilisateurs.id
           WHERE recoltes.id = ?""", (recolte_id,)
    ).fetchone()


def message_nouvelle_commande(produits):
    return (f"App Agricole : nouvelle commande de {session['nom']} pour {', '.join(produits)}. "
            "Connecte-toi pour la confirmer.")


def recolte_commandable(recolte):
    return recolte is not None and recolte["statut"] == "disponible"


@app.route("/panier/ajouter/<int:recolte_id>", methods=["POST"])
def ajouter_au_panier(recolte_id):
    if not utilisateur_connecte() or session["role"] != "client":
        return redirect(url_for("connexion"))

    try:
        quantite = quantite_valide(request.form.get("quantite", ""))
    except ValueError as erreur:
        flash(str(erreur))
        return redirect(url_for("espace_client"))

    connexion_bd = get_connexion()
    recolte = get_recolte_avec_agriculteur(connexion_bd, recolte_id)
    connexion_bd.close()
    if not recolte_commandable(recolte):
        flash("Cette récolte n'est plus disponible.")
        return redirect(url_for("espace_client"))

    panier = session.get("panier", [])
    panier.append({"recolte_id": recolte_id, "quantite": quantite})
    session["panier"] = panier

    flash("Ajouté au panier.")
    return redirect(url_for("espace_client"))


@app.route("/panier")
def voir_panier():
    if not utilisateur_connecte() or session["role"] != "client":
        return redirect(url_for("connexion"))

    connexion_bd = get_connexion()
    articles = []
    for index, item in enumerate(session.get("panier", [])):
        recolte = get_recolte_avec_agriculteur(connexion_bd, item["recolte_id"])
        if recolte:
            articles.append({"index": index, "recolte": recolte, "quantite": item["quantite"]})
    connexion_bd.close()

    return render_template("panier.html", nom=session["nom"], articles=articles, modes_livraison=MODES_LIVRAISON)


@app.route("/panier/supprimer/<int:index>", methods=["POST"])
def supprimer_du_panier(index):
    if not utilisateur_connecte() or session["role"] != "client":
        return redirect(url_for("connexion"))

    panier = session.get("panier", [])
    if 0 <= index < len(panier):
        panier.pop(index)
        session["panier"] = panier

    return redirect(url_for("voir_panier"))


@app.route("/panier/valider", methods=["POST"])
def valider_panier():
    if not utilisateur_connecte() or session["role"] != "client":
        return redirect(url_for("connexion"))

    panier = session.get("panier", [])
    if not panier:
        flash("Ton panier est vide.")
        return redirect(url_for("espace_client"))

    try:
        mode_livraison, adresse_livraison = livraison_valide(request.form)
    except ValueError as erreur:
        flash(str(erreur))
        return redirect(url_for("voir_panier"))

    connexion_bd = get_connexion()
    envoyees, indisponibles = 0, []
    produits_par_telephone = {}  # un seul SMS par agriculteur
    for item in panier:
        recolte = get_recolte_avec_agriculteur(connexion_bd, item["recolte_id"])
        if not recolte_commandable(recolte):
            indisponibles.append(recolte["nom"] if recolte else "une récolte supprimée")
            continue
        connexion_bd.execute(
            """INSERT INTO commandes (recolte_id, client_id, quantite_demandee, message, mode_livraison, adresse_livraison)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (item["recolte_id"], session["utilisateur_id"], item["quantite"], "Commande depuis le panier",
             mode_livraison, adresse_livraison)
        )
        envoyees += 1
        if recolte["telephone_agriculteur"]:
            produits_par_telephone.setdefault(recolte["telephone_agriculteur"], []).append(recolte["nom"])
    connexion_bd.commit()
    connexion_bd.close()

    for telephone, produits in produits_par_telephone.items():
        sms.alerter(telephone, message_nouvelle_commande(produits))

    session["panier"] = []
    if indisponibles:
        flash("Plus disponible, non commandé : " + ", ".join(indisponibles) + ".")
    if envoyees:
        flash("Tes commandes ont été envoyées aux agriculteurs concernés.")
        return redirect(url_for("mes_commandes"))
    return redirect(url_for("espace_client"))


@app.route("/commander/<int:recolte_id>", methods=["GET", "POST"])
def commander(recolte_id):
    if not utilisateur_connecte() or session["role"] != "client":
        return redirect(url_for("connexion"))

    connexion_bd = get_connexion()
    recolte = connexion_bd.execute(
        """SELECT recoltes.*, utilisateurs.nom AS nom_agriculteur,
                  utilisateurs.telephone AS telephone_agriculteur
           FROM recoltes JOIN utilisateurs ON recoltes.agriculteur_id = utilisateurs.id
           WHERE recoltes.id = ?""", (recolte_id,)
    ).fetchone()

    if not recolte_commandable(recolte):
        connexion_bd.close()
        flash("Cette récolte n'est plus disponible.")
        return redirect(url_for("espace_client"))

    if request.method == "POST":
        try:
            quantite_demandee = quantite_valide(request.form["quantite_demandee"])
            mode_livraison, adresse_livraison = livraison_valide(request.form)
        except ValueError as erreur:
            connexion_bd.close()
            flash(str(erreur))
            return redirect(url_for("commander", recolte_id=recolte_id))
        message = request.form.get("message", "")

        connexion_bd.execute(
            """INSERT INTO commandes (recolte_id, client_id, quantite_demandee, message, mode_livraison, adresse_livraison)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (recolte_id, session["utilisateur_id"], quantite_demandee, message, mode_livraison, adresse_livraison)
        )
        connexion_bd.commit()
        connexion_bd.close()
        sms.alerter(recolte["telephone_agriculteur"], message_nouvelle_commande([recolte["nom"]]))

        flash(f"Ta commande a été envoyée à {recolte['nom_agriculteur']}. Il te contactera pour la suite.")
        return redirect(url_for("mes_commandes"))

    connexion_bd.close()
    return render_template("commander.html", recolte=recolte, modes_livraison=MODES_LIVRAISON)


@app.route("/mes-commandes")
def mes_commandes():
    if not utilisateur_connecte() or session["role"] != "client":
        return redirect(url_for("connexion"))

    connexion_bd = get_connexion()
    commandes = connexion_bd.execute(
        """SELECT commandes.*, recoltes.nom AS nom_recolte, recoltes.prix, recoltes.agriculteur_id,
                  utilisateurs.nom AS nom_agriculteur, utilisateurs.email AS email_agriculteur,
                  utilisateurs.telephone AS telephone_agriculteur, avis.note AS note_avis
           FROM commandes
           JOIN recoltes ON commandes.recolte_id = recoltes.id
           JOIN utilisateurs ON recoltes.agriculteur_id = utilisateurs.id
           LEFT JOIN avis ON avis.commande_id = commandes.id
           WHERE commandes.client_id = ?
           ORDER BY commandes.date_creation DESC""",
        (session["utilisateur_id"],)
    ).fetchall()
    # Les mises à jour affichées ici sont considérées comme vues
    connexion_bd.execute("UPDATE commandes SET lu_client = 1 WHERE client_id = ?", (session["utilisateur_id"],))
    connexion_bd.commit()
    connexion_bd.close()

    return render_template("mes_commandes.html", nom=session["nom"], commandes=commandes,
                           modes_livraison=MODES_LIVRAISON)


@app.route("/mes-commandes/<int:commande_id>/annuler", methods=["POST"])
def annuler_commande(commande_id):
    if not utilisateur_connecte() or session["role"] != "client":
        return redirect(url_for("connexion"))

    # Le client ne peut annuler que ses propres commandes, tant qu'elles sont en attente
    connexion_bd = get_connexion()
    resultat = connexion_bd.execute(
        "UPDATE commandes SET statut = 'annulee', lu = 0 WHERE id = ? AND client_id = ? AND statut = 'en_attente'",
        (commande_id, session["utilisateur_id"])
    )
    connexion_bd.commit()
    if resultat.rowcount:
        commande = connexion_bd.execute(
            """SELECT recoltes.nom, utilisateurs.telephone FROM commandes
               JOIN recoltes ON commandes.recolte_id = recoltes.id
               JOIN utilisateurs ON recoltes.agriculteur_id = utilisateurs.id
               WHERE commandes.id = ?""", (commande_id,)
        ).fetchone()
        sms.alerter(commande["telephone"],
                    f"App Agricole : {session['nom']} a annulé sa commande de {commande['nom']}.")
    connexion_bd.close()

    if resultat.rowcount:
        flash("Commande annulée.")
    else:
        flash("Cette commande ne peut plus être annulée.")
    return redirect(url_for("mes_commandes"))
