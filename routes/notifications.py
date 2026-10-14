"""Notifications et tableau de bord."""
from flask import render_template, redirect, url_for, session
from database import get_connexion
from core import app, utilisateur_connecte


def compter_notifications_non_lues(utilisateur_id, role):
    """Compte le nombre total de notifications non lues pour l'utilisateur connecté."""
    connexion_bd = get_connexion()
    # Messages non lus dans les discussions de commandes
    total = connexion_bd.execute(
        "SELECT COUNT(*) AS n FROM messages_commande WHERE destinataire_id = ? AND lu = 0", (utilisateur_id,)
    ).fetchone()["n"]

    if role == "agriculteur":
        r = connexion_bd.execute(
            """SELECT COUNT(*) AS n FROM commandes
               JOIN recoltes ON commandes.recolte_id = recoltes.id
               WHERE recoltes.agriculteur_id = ? AND commandes.lu = 0""",
            (utilisateur_id,)
        ).fetchone()
        total += r["n"]
        r = connexion_bd.execute(
            """SELECT COUNT(*) AS n FROM contacts_demande
               JOIN demandes_financement ON contacts_demande.demande_id = demandes_financement.id
               WHERE demandes_financement.agriculteur_id = ? AND contacts_demande.lu = 0""",
            (utilisateur_id,)
        ).fetchone()
        total += r["n"]

    elif role == "client":
        r = connexion_bd.execute(
            "SELECT COUNT(*) AS n FROM commandes WHERE client_id = ? AND lu_client = 0",
            (utilisateur_id,)
        ).fetchone()
        total += r["n"]

    elif role == "fournisseur":
        r = connexion_bd.execute(
            """SELECT COUNT(*) AS n FROM contacts_fournisseur
               JOIN produits_fournisseur ON contacts_fournisseur.produit_id = produits_fournisseur.id
               WHERE produits_fournisseur.fournisseur_id = ? AND contacts_fournisseur.lu = 0""",
            (utilisateur_id,)
        ).fetchone()
        total += r["n"]

    elif role == "financeur":
        r = connexion_bd.execute(
            """SELECT COUNT(*) AS n FROM contacts_offre
               JOIN offres_financement ON contacts_offre.offre_id = offres_financement.id
               WHERE offres_financement.financeur_id = ? AND contacts_offre.lu = 0""",
            (utilisateur_id,)
        ).fetchone()
        total += r["n"]

    connexion_bd.close()
    return total


@app.context_processor
def injecter_notifications():
    """Rend le nombre de notifications non lues disponible dans tous les templates (badge du menu)."""
    if utilisateur_connecte():
        return {"nb_notifications": compter_notifications_non_lues(session["utilisateur_id"], session["role"])}
    return {"nb_notifications": 0}


@app.route("/notifications")
def notifications():
    if not utilisateur_connecte():
        return redirect(url_for("connexion"))

    role = session["role"]
    utilisateur_id = session["utilisateur_id"]
    connexion_bd = get_connexion()

    commandes = []
    messages_financement = []
    messages_fournisseur = []
    interets_offre = []
    commandes_client = []
    # Discussions avec des messages non lus (marqués lus à l'ouverture de la discussion)
    discussions = connexion_bd.execute(
        """SELECT commande_id, COUNT(*) AS nombre, MAX(recoltes.nom) AS nom_recolte,
                  MAX(utilisateurs.nom) AS nom_auteur
           FROM messages_commande
           JOIN commandes ON messages_commande.commande_id = commandes.id
           JOIN recoltes ON commandes.recolte_id = recoltes.id
           JOIN utilisateurs ON messages_commande.auteur_id = utilisateurs.id
           WHERE messages_commande.destinataire_id = ? AND messages_commande.lu = 0
           GROUP BY commande_id""",
        (utilisateur_id,)
    ).fetchall()

    if role == "agriculteur":
        commandes = connexion_bd.execute(
            """SELECT commandes.*, recoltes.nom AS nom_recolte,
                      utilisateurs.nom AS nom_client
               FROM commandes
               JOIN recoltes ON commandes.recolte_id = recoltes.id
               JOIN utilisateurs ON commandes.client_id = utilisateurs.id
               WHERE recoltes.agriculteur_id = ?
               ORDER BY commandes.lu ASC, commandes.date_creation DESC""",
            (utilisateur_id,)
        ).fetchall()
        messages_financement = connexion_bd.execute(
            """SELECT contacts_demande.*, demandes_financement.objet,
                      utilisateurs.nom AS nom_financeur
               FROM contacts_demande
               JOIN demandes_financement ON contacts_demande.demande_id = demandes_financement.id
               JOIN utilisateurs ON contacts_demande.financeur_id = utilisateurs.id
               WHERE demandes_financement.agriculteur_id = ?
               ORDER BY contacts_demande.lu ASC, contacts_demande.date_creation DESC""",
            (utilisateur_id,)
        ).fetchall()
        connexion_bd.execute(
            """UPDATE commandes SET lu = 1 WHERE recolte_id IN
               (SELECT id FROM recoltes WHERE agriculteur_id = ?)""",
            (utilisateur_id,)
        )
        connexion_bd.execute(
            """UPDATE contacts_demande SET lu = 1 WHERE demande_id IN
               (SELECT id FROM demandes_financement WHERE agriculteur_id = ?)""",
            (utilisateur_id,)
        )

    elif role == "client":
        commandes_client = connexion_bd.execute(
            """SELECT commandes.*, recoltes.nom AS nom_recolte, utilisateurs.nom AS nom_agriculteur
               FROM commandes
               JOIN recoltes ON commandes.recolte_id = recoltes.id
               JOIN utilisateurs ON recoltes.agriculteur_id = utilisateurs.id
               WHERE commandes.client_id = ? AND commandes.statut != 'en_attente'
               ORDER BY commandes.lu_client ASC, commandes.date_creation DESC""",
            (utilisateur_id,)
        ).fetchall()
        connexion_bd.execute("UPDATE commandes SET lu_client = 1 WHERE client_id = ?", (utilisateur_id,))

    elif role == "fournisseur":
        messages_fournisseur = connexion_bd.execute(
            """SELECT contacts_fournisseur.*, produits_fournisseur.nom AS nom_produit,
                      utilisateurs.nom AS nom_agriculteur, utilisateurs.email AS email_agriculteur
               FROM contacts_fournisseur
               JOIN produits_fournisseur ON contacts_fournisseur.produit_id = produits_fournisseur.id
               JOIN utilisateurs ON contacts_fournisseur.agriculteur_id = utilisateurs.id
               WHERE produits_fournisseur.fournisseur_id = ?
               ORDER BY contacts_fournisseur.lu ASC, contacts_fournisseur.date_creation DESC""",
            (utilisateur_id,)
        ).fetchall()
        connexion_bd.execute(
            """UPDATE contacts_fournisseur SET lu = 1 WHERE produit_id IN
               (SELECT id FROM produits_fournisseur WHERE fournisseur_id = ?)""",
            (utilisateur_id,)
        )

    elif role == "financeur":
        interets_offre = connexion_bd.execute(
            """SELECT contacts_offre.*, offres_financement.nom AS nom_offre,
                      utilisateurs.nom AS nom_agriculteur, utilisateurs.email AS email_agriculteur
               FROM contacts_offre
               JOIN offres_financement ON contacts_offre.offre_id = offres_financement.id
               JOIN utilisateurs ON contacts_offre.agriculteur_id = utilisateurs.id
               WHERE offres_financement.financeur_id = ?
               ORDER BY contacts_offre.lu ASC, contacts_offre.date_creation DESC""",
            (utilisateur_id,)
        ).fetchall()
        connexion_bd.execute(
            """UPDATE contacts_offre SET lu = 1 WHERE offre_id IN
               (SELECT id FROM offres_financement WHERE financeur_id = ?)""",
            (utilisateur_id,)
        )

    connexion_bd.commit()
    connexion_bd.close()

    return render_template(
        "notifications.html", role=role, commandes=commandes,
        messages_financement=messages_financement,
        messages_fournisseur=messages_fournisseur, interets_offre=interets_offre,
        commandes_client=commandes_client, discussions=discussions
    )


@app.route("/tableau-de-bord")
def tableau_de_bord():
    if not utilisateur_connecte():
        return redirect(url_for("connexion"))

    role = session["role"]
    # Agriculteurs et clients : leur espace sert de tableau de bord (chiffres et raccourcis)
    if role in ("agriculteur", "client"):
        return redirect(url_for(f"espace_{role}"))
    utilisateur_id = session["utilisateur_id"]
    connexion_bd = get_connexion()
    stats = {}

    if role == "agriculteur":
        stats["recoltes_total"] = connexion_bd.execute(
            "SELECT COUNT(*) AS n FROM recoltes WHERE agriculteur_id = ?", (utilisateur_id,)
        ).fetchone()["n"]
        stats["recoltes_disponibles"] = connexion_bd.execute(
            "SELECT COUNT(*) AS n FROM recoltes WHERE agriculteur_id = ? AND statut = 'disponible'",
            (utilisateur_id,)
        ).fetchone()["n"]
        stats["commandes_recues"] = connexion_bd.execute(
            """SELECT COUNT(*) AS n FROM commandes
               JOIN recoltes ON commandes.recolte_id = recoltes.id
               WHERE recoltes.agriculteur_id = ?""",
            (utilisateur_id,)
        ).fetchone()["n"]
        stats["demandes_financement"] = connexion_bd.execute(
            "SELECT COUNT(*) AS n FROM demandes_financement WHERE agriculteur_id = ?", (utilisateur_id,)
        ).fetchone()["n"]

    elif role == "fournisseur":
        stats["produits_total"] = connexion_bd.execute(
            "SELECT COUNT(*) AS n FROM produits_fournisseur WHERE fournisseur_id = ?", (utilisateur_id,)
        ).fetchone()["n"]
        stats["produits_disponibles"] = connexion_bd.execute(
            "SELECT COUNT(*) AS n FROM produits_fournisseur WHERE fournisseur_id = ? AND statut = 'disponible'",
            (utilisateur_id,)
        ).fetchone()["n"]
        stats["messages_recus"] = connexion_bd.execute(
            """SELECT COUNT(*) AS n FROM contacts_fournisseur
               JOIN produits_fournisseur ON contacts_fournisseur.produit_id = produits_fournisseur.id
               WHERE produits_fournisseur.fournisseur_id = ?""",
            (utilisateur_id,)
        ).fetchone()["n"]

    elif role == "financeur":
        stats["offres_total"] = connexion_bd.execute(
            "SELECT COUNT(*) AS n FROM offres_financement WHERE financeur_id = ?", (utilisateur_id,)
        ).fetchone()["n"]
        stats["offres_actives"] = connexion_bd.execute(
            "SELECT COUNT(*) AS n FROM offres_financement WHERE financeur_id = ? AND statut = 'active'",
            (utilisateur_id,)
        ).fetchone()["n"]
        stats["interets_recus"] = connexion_bd.execute(
            """SELECT COUNT(*) AS n FROM contacts_offre
               JOIN offres_financement ON contacts_offre.offre_id = offres_financement.id
               WHERE offres_financement.financeur_id = ?""",
            (utilisateur_id,)
        ).fetchone()["n"]
        stats["demandes_ouvertes"] = connexion_bd.execute(
            "SELECT COUNT(*) AS n FROM demandes_financement WHERE statut = 'ouverte'"
        ).fetchone()["n"]

    elif role == "client":
        stats["commandes_passees"] = connexion_bd.execute(
            "SELECT COUNT(*) AS n FROM commandes WHERE client_id = ?", (utilisateur_id,)
        ).fetchone()["n"]

    connexion_bd.close()
    return render_template("tableau_de_bord.html", role=role, stats=stats)
