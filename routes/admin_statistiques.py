"""Tableau de bord de l'admin : évolution mois par mois (inscriptions, annonces, commandes,
ventes, revenus de la plateforme) et classements (produits, localités, agriculteurs)."""
from flask import render_template
from database import get_connexion
from core import app
from routes.premium import admin_requis
from routes.statistiques import derniers_mois, NOMS_MOIS

NOMBRE_MOIS = 12


def compter_par_mois(connexion_bd, requete, debut):
    """{'2026-10': {colonnes...}} pour une requête qui regroupe par SUBSTR(date, 1, 7) AS mois."""
    return {ligne["mois"]: ligne for ligne in connexion_bd.execute(requete, (debut,)).fetchall()}


@app.route("/admin/statistiques")
@admin_requis
def admin_statistiques():
    liste_mois = derniers_mois(NOMBRE_MOIS)
    debut = liste_mois[0]
    connexion_bd = get_connexion()

    inscriptions = compter_par_mois(connexion_bd, """
        SELECT SUBSTR(date_inscription, 1, 7) AS mois,
               SUM(CASE WHEN role = 'agriculteur' THEN 1 ELSE 0 END) AS agriculteurs,
               SUM(CASE WHEN role = 'client' THEN 1 ELSE 0 END) AS clients,
               COUNT(*) AS total
        FROM utilisateurs WHERE SUBSTR(date_inscription, 1, 7) >= ?
        GROUP BY SUBSTR(date_inscription, 1, 7)""", debut)
    annonces = compter_par_mois(connexion_bd, """
        SELECT SUBSTR(date_creation, 1, 7) AS mois, COUNT(*) AS n
        FROM recoltes WHERE SUBSTR(date_creation, 1, 7) >= ?
        GROUP BY SUBSTR(date_creation, 1, 7)""", debut)
    commandes = compter_par_mois(connexion_bd, """
        SELECT SUBSTR(date_creation, 1, 7) AS mois, COUNT(*) AS passees,
               SUM(CASE WHEN statut = 'livree' THEN 1 ELSE 0 END) AS livrees,
               COALESCE(SUM(CASE WHEN statut = 'livree' THEN montant END), 0) AS ventes,
               COALESCE(SUM(CASE WHEN statut = 'livree' THEN commission END), 0) AS commissions
        FROM commandes WHERE SUBSTR(date_creation, 1, 7) >= ?
        GROUP BY SUBSTR(date_creation, 1, 7)""", debut)
    premium = compter_par_mois(connexion_bd, """
        SELECT SUBSTR(date_creation, 1, 7) AS mois, COALESCE(SUM(montant), 0) AS montant
        FROM paiements_premium WHERE statut = 'valide' AND SUBSTR(date_creation, 1, 7) >= ?
        GROUP BY SUBSTR(date_creation, 1, 7)""", debut)

    mois = []
    for cle in liste_mois:
        inscrits, commande = inscriptions.get(cle), commandes.get(cle)
        commissions = commande["commissions"] if commande else 0
        abonnements = premium[cle]["montant"] if cle in premium else 0
        mois.append({
            "libelle": f"{NOMS_MOIS[int(cle[5:]) - 1]} {cle[2:4]}",
            "agriculteurs": inscrits["agriculteurs"] if inscrits else 0,
            "clients": inscrits["clients"] if inscrits else 0,
            "inscrits": inscrits["total"] if inscrits else 0,
            "annonces": annonces[cle]["n"] if cle in annonces else 0,
            "commandes": commande["passees"] if commande else 0,
            "livrees": commande["livrees"] if commande else 0,
            "ventes": commande["ventes"] if commande else 0,
            "commissions": commissions,
            "premium": abonnements,
            "revenus": commissions + abonnements,
        })
    maximum = max([m["revenus"] for m in mois] + [1])
    for m in mois:
        m["pourcentage"] = round(100 * m["revenus"] / maximum)

    classements = {
        "produits": connexion_bd.execute("""
            SELECT recoltes.nom AS libelle, COUNT(*) AS commandes, COALESCE(SUM(commandes.montant), 0) AS ventes
            FROM commandes JOIN recoltes ON commandes.recolte_id = recoltes.id
            WHERE commandes.statut = 'livree'
            GROUP BY recoltes.nom ORDER BY COALESCE(SUM(commandes.montant), 0) DESC LIMIT 5""").fetchall(),
        "localites": connexion_bd.execute("""
            SELECT recoltes.localite AS libelle, COUNT(*) AS commandes, COALESCE(SUM(commandes.montant), 0) AS ventes
            FROM commandes JOIN recoltes ON commandes.recolte_id = recoltes.id
            WHERE commandes.statut = 'livree'
            GROUP BY recoltes.localite ORDER BY COALESCE(SUM(commandes.montant), 0) DESC LIMIT 5""").fetchall(),
        "agriculteurs": connexion_bd.execute("""
            SELECT utilisateurs.nom AS libelle, COUNT(*) AS commandes, COALESCE(SUM(commandes.montant), 0) AS ventes
            FROM commandes JOIN recoltes ON commandes.recolte_id = recoltes.id
            JOIN utilisateurs ON recoltes.agriculteur_id = utilisateurs.id
            WHERE commandes.statut = 'livree'
            GROUP BY utilisateurs.id, utilisateurs.nom
            ORDER BY COALESCE(SUM(commandes.montant), 0) DESC LIMIT 5""").fetchall(),
    }
    actifs = {
        # Agriculteurs avec au moins une annonce en ligne, clients ayant déjà commandé
        "agriculteurs": connexion_bd.execute(
            """SELECT COUNT(DISTINCT agriculteur_id) AS n FROM recoltes
               WHERE statut = 'disponible' AND masquee = 0""").fetchone()["n"],
        "clients": connexion_bd.execute("SELECT COUNT(DISTINCT client_id) AS n FROM commandes").fetchone()["n"],
    }
    par_statut = {ligne["statut"]: ligne["n"] for ligne in connexion_bd.execute(
        "SELECT statut, COUNT(*) AS n FROM commandes GROUP BY statut").fetchall()}
    connexion_bd.close()

    traitees = par_statut.get("livree", 0) + par_statut.get("annulee", 0)
    return render_template(
        "admin_statistiques.html", mois=mois, classements=classements, actifs=actifs,
        taux_livraison=round(100 * par_statut.get("livree", 0) / traitees) if traitees else None,
        totaux={cle: sum(m[cle] for m in mois) for cle in
                ("inscrits", "annonces", "commandes", "livrees", "ventes", "commissions", "premium", "revenus")},
    )
