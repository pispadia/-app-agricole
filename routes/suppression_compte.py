"""Suppression de compte à la demande de l'utilisateur (droit à l'effacement).

Les données personnelles sont effacées ; les commandes passées restent (comptabilité),
rattachées à un compte anonyme « Compte supprimé ». Refusée tant qu'une commande est en
cours ou qu'une commission reste due, pour ne léser personne."""
import secrets

from flask import flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from database import get_connexion
from core import app, utilisateur_connecte


def obstacles_suppression(connexion_bd, utilisateur_id):
    """Raisons qui empêchent de supprimer le compte tout de suite (liste vide = possible)."""
    obstacles = []
    en_cours = connexion_bd.execute(
        """SELECT COUNT(*) AS n FROM commandes JOIN recoltes ON commandes.recolte_id = recoltes.id
           WHERE commandes.statut IN ('en_attente', 'confirmee')
             AND (commandes.client_id = ? OR recoltes.agriculteur_id = ?)""",
        (utilisateur_id, utilisateur_id)).fetchone()["n"]
    if en_cours:
        obstacles.append(f"{en_cours} commande(s) en cours : livre-les ou annule-les d'abord.")
    commissions = connexion_bd.execute(
        """SELECT COALESCE(SUM(commandes.commission), 0) AS total FROM commandes
           JOIN recoltes ON commandes.recolte_id = recoltes.id
           WHERE recoltes.agriculteur_id = ? AND commandes.statut = 'livree'
             AND commandes.commission_payee = 0 AND commandes.paye_en_ligne = 0""",
        (utilisateur_id,)).fetchone()["total"]
    if commissions:
        obstacles.append(f"Commission due à la plateforme : {commissions} FCFA, à régler d'abord.")
    return obstacles


def effacer_compte(connexion_bd, utilisateur_id):
    connexion_bd.execute(
        """UPDATE utilisateurs SET nom = 'Compte supprimé', email = ?, mot_de_passe = ?, telephone = NULL,
                  email_confirme = NULL, code_parrainage = NULL, suspendu = 1, verification = NULL
           WHERE id = ?""",
        (f"supprime-{utilisateur_id}@compte-supprime.invalid",
         generate_password_hash(secrets.token_urlsafe(32)), utilisateur_id))
    # Annonces et offres retirées (gardées pour l'historique des commandes)
    connexion_bd.execute("UPDATE recoltes SET statut = 'epuise', masquee = 1, photo = NULL, description = NULL "
                         "WHERE agriculteur_id = ?", (utilisateur_id,))
    connexion_bd.execute("DELETE FROM photos_recolte WHERE recolte_id IN "
                         "(SELECT id FROM recoltes WHERE agriculteur_id = ?)", (utilisateur_id,))
    connexion_bd.execute("UPDATE produits_fournisseur SET statut = 'epuise', photo = NULL WHERE fournisseur_id = ?",
                         (utilisateur_id,))
    connexion_bd.execute("UPDATE offres_financement SET statut = 'fermee' WHERE financeur_id = ?", (utilisateur_id,))
    connexion_bd.execute("UPDATE demandes_financement SET statut = 'traitee' WHERE agriculteur_id = ?",
                         (utilisateur_id,))
    # Adresses de livraison effacées des commandes
    connexion_bd.execute("UPDATE commandes SET adresse_livraison = NULL WHERE client_id = ?", (utilisateur_id,))
    for table, colonne in (("alertes_produit", "client_id"), ("abonnements_push", "utilisateur_id"),
                           ("commandes_regulieres", "client_id"), ("favoris", "client_id"),
                           ("agriculteurs_suivis", "client_id"), ("agriculteurs_suivis", "agriculteur_id"),
                           ("avis_clients", "client_id"),
                           ("verifications", "utilisateur_id")):
        connexion_bd.execute(f"DELETE FROM {table} WHERE {colonne} = ?", (utilisateur_id,))
    connexion_bd.commit()


@app.route("/mon-profil/supprimer", methods=["GET", "POST"])
def supprimer_compte():
    if not utilisateur_connecte():
        return redirect(url_for("connexion"))
    utilisateur_id = session["utilisateur_id"]
    connexion_bd = get_connexion()
    obstacles = obstacles_suppression(connexion_bd, utilisateur_id)

    if request.method == "POST" and not obstacles:
        utilisateur = connexion_bd.execute(
            "SELECT mot_de_passe FROM utilisateurs WHERE id = ?", (utilisateur_id,)).fetchone()
        if request.form.get("confirmation", "").strip().upper() != "SUPPRIMER":
            flash("Écris SUPPRIMER pour confirmer.")
        elif not check_password_hash(utilisateur["mot_de_passe"], request.form.get("mot_de_passe", "")):
            flash("Mot de passe incorrect.")
        else:
            effacer_compte(connexion_bd, utilisateur_id)
            connexion_bd.close()
            langue = session.get("langue")
            session.clear()
            if langue:
                session["langue"] = langue
            flash("Ton compte a été supprimé. Merci d'avoir utilisé App Agricole.")
            return redirect(url_for("accueil"))

    connexion_bd.close()
    return render_template("supprimer_compte.html", obstacles=obstacles)
