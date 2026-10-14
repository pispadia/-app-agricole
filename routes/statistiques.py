"""Statistiques de l'agriculteur : ventes, chiffre d'affaires, produits les plus demandés.
Les chiffres clés sont pour tous ; le détail par mois et par produit est réservé au Premium."""
from datetime import date

from flask import render_template, redirect, url_for, session
from database import get_connexion
from core import app, utilisateur_connecte, est_premium
from routes.avis import NOTES_AGRICULTEURS

NOMBRE_MOIS = 12
NOMS_MOIS = ("janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc.")


def derniers_mois(nombre, aujourdhui=None):
    """['2025-11', ..., '2026-10'] : les `nombre` derniers mois, le mois en cours compris."""
    aujourdhui = aujourdhui or date.today()
    annee, mois = aujourdhui.year, aujourdhui.month
    resultat = []
    for _ in range(nombre):
        resultat.append(f"{annee:04d}-{mois:02d}")
        mois -= 1
        if mois == 0:
            annee, mois = annee - 1, 12
    return list(reversed(resultat))


@app.route("/espace-agriculteur/statistiques")
def statistiques_agriculteur():
    if not utilisateur_connecte() or session["role"] != "agriculteur":
        return redirect(url_for("connexion"))

    agriculteur_id = session["utilisateur_id"]
    connexion_bd = get_connexion()
    par_statut = {ligne["statut"]: ligne["n"] for ligne in connexion_bd.execute(
        """SELECT commandes.statut, COUNT(*) AS n FROM commandes
           JOIN recoltes ON commandes.recolte_id = recoltes.id
           WHERE recoltes.agriculteur_id = ? GROUP BY commandes.statut""", (agriculteur_id,)
    ).fetchall()}
    ventes = connexion_bd.execute(
        """SELECT COALESCE(SUM(commandes.montant), 0) AS chiffre_affaires,
                  COALESCE(SUM(commandes.commission), 0) AS commissions
           FROM commandes JOIN recoltes ON commandes.recolte_id = recoltes.id
           WHERE recoltes.agriculteur_id = ? AND commandes.statut = 'livree'""", (agriculteur_id,)
    ).fetchone()
    notes = connexion_bd.execute(
        f"SELECT note_moyenne, nb_avis FROM {NOTES_AGRICULTEURS} notes WHERE agriculteur_id = ?", (agriculteur_id,)
    ).fetchone()

    premium = est_premium()
    mois, produits = [], []
    if premium:
        liste_mois = derniers_mois(NOMBRE_MOIS)
        par_mois = {ligne["mois"]: ligne for ligne in connexion_bd.execute(
            """SELECT SUBSTR(commandes.date_creation, 1, 7) AS mois, COUNT(*) AS ventes,
                      COALESCE(SUM(commandes.montant), 0) AS montant
               FROM commandes JOIN recoltes ON commandes.recolte_id = recoltes.id
               WHERE recoltes.agriculteur_id = ? AND commandes.statut = 'livree'
                 AND SUBSTR(commandes.date_creation, 1, 7) >= ?
               GROUP BY SUBSTR(commandes.date_creation, 1, 7)""", (agriculteur_id, liste_mois[0])
        ).fetchall()}
        maximum = max([ligne["montant"] for ligne in par_mois.values()] + [1])
        for cle in liste_mois:
            ligne = par_mois.get(cle)
            montant = ligne["montant"] if ligne else 0
            mois.append({"libelle": f"{NOMS_MOIS[int(cle[5:]) - 1]} {cle[2:4]}", "montant": montant,
                         "ventes": ligne["ventes"] if ligne else 0, "pourcentage": round(100 * montant / maximum)})
        produits = connexion_bd.execute(
            """SELECT recoltes.nom, COUNT(*) AS commandes,
                      SUM(CASE WHEN commandes.statut = 'livree' THEN 1 ELSE 0 END) AS livrees,
                      COALESCE(SUM(CASE WHEN commandes.statut = 'livree' THEN commandes.montant END), 0) AS montant
               FROM commandes JOIN recoltes ON commandes.recolte_id = recoltes.id
               WHERE recoltes.agriculteur_id = ?
               GROUP BY recoltes.nom ORDER BY COUNT(*) DESC, recoltes.nom LIMIT 5""", (agriculteur_id,)
        ).fetchall()
    connexion_bd.close()

    total = sum(par_statut.values())
    traitees = total - par_statut.get("en_attente", 0)
    acceptees = par_statut.get("confirmee", 0) + par_statut.get("livree", 0)
    return render_template(
        "statistiques.html", par_statut=par_statut, total=total, ventes=ventes, notes=notes,
        taux_acceptation=round(100 * acceptees / traitees) if traitees else None,
        premium=premium, mois=mois, produits=produits,
    )
