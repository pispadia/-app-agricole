"""Export comptable pour l'admin : fichiers CSV ouverts directement par Excel (séparateur « ; »,
encodage UTF-8 avec BOM pour les accents), et récapitulatif des revenus par mois."""
import csv
import io
from datetime import date

from flask import render_template, request, Response
from database import get_connexion
from core import app
from routes.premium import admin_requis


def cellule_sure(valeur):
    """Un texte saisi par un utilisateur qui commence par = + - @ serait exécuté comme une
    formule par Excel : on le préfixe d'une apostrophe pour qu'il reste du texte."""
    if isinstance(valeur, str) and valeur[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + valeur
    return valeur


def reponse_csv(nom_fichier, entetes, lignes):
    tampon = io.StringIO()
    tampon.write("﻿")  # BOM : Excel reconnaît l'UTF-8 (accents)
    ecrivain = csv.writer(tampon, delimiter=";")
    ecrivain.writerow(entetes)
    ecrivain.writerows([cellule_sure(valeur) for valeur in ligne] for ligne in lignes)
    return Response(tampon.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{nom_fichier}"'})


def annee_demandee():
    annee = request.args.get("annee", "")
    return annee if annee.isdigit() and len(annee) == 4 else str(date.today().year)


def oui_non(valeur):
    return "oui" if valeur else "non"


@app.route("/admin/export")
@admin_requis
def export_comptable():
    annee = annee_demandee()
    connexion_bd = get_connexion()
    # Revenus de la plateforme par mois : commissions réglées et abonnements Premium validés
    commissions = {ligne["mois"]: ligne for ligne in connexion_bd.execute(
        """SELECT SUBSTR(date_creation, 1, 7) AS mois, COUNT(*) AS ventes, COALESCE(SUM(montant), 0) AS ventes_montant,
                  COALESCE(SUM(CASE WHEN commission_payee = 1 THEN commission ELSE 0 END), 0) AS commissions
           FROM commandes WHERE statut = 'livree' AND SUBSTR(date_creation, 1, 4) = ?
           GROUP BY SUBSTR(date_creation, 1, 7)""", (annee,)
    ).fetchall()}
    premium = {ligne["mois"]: ligne["montant"] for ligne in connexion_bd.execute(
        """SELECT SUBSTR(date_creation, 1, 7) AS mois, COALESCE(SUM(montant), 0) AS montant
           FROM paiements_premium WHERE statut = 'valide' AND SUBSTR(date_creation, 1, 4) = ?
           GROUP BY SUBSTR(date_creation, 1, 7)""", (annee,)
    ).fetchall()}
    connexion_bd.close()

    mois = []
    for numero in range(1, 13):
        cle = f"{annee}-{numero:02d}"
        ligne = commissions.get(cle)
        mois.append({
            "mois": cle, "ventes": ligne["ventes"] if ligne else 0,
            "ventes_montant": ligne["ventes_montant"] if ligne else 0,
            "commissions": ligne["commissions"] if ligne else 0, "premium": premium.get(cle, 0),
        })
    totaux = {cle: sum(m[cle] for m in mois) for cle in ("ventes", "ventes_montant", "commissions", "premium")}
    return render_template("export.html", annee=annee, mois=mois, totaux=totaux)


@app.route("/admin/export/ventes.csv")
@admin_requis
def export_ventes():
    annee = annee_demandee()
    connexion_bd = get_connexion()
    lignes = connexion_bd.execute(
        """SELECT commandes.id, SUBSTR(commandes.date_creation, 1, 10) AS jour, commandes.statut,
                  recoltes.nom AS produit, commandes.quantite_demandee, agriculteurs.nom AS agriculteur,
                  clients.nom AS client, commandes.mode_paiement, commandes.montant, commandes.frais_livraison,
                  commandes.commission, commandes.commission_payee, commandes.paye_en_ligne,
                  commandes.montant_a_payer, commandes.reverse_agriculteur, commandes.rembourse
           FROM commandes
           JOIN recoltes ON commandes.recolte_id = recoltes.id
           JOIN utilisateurs agriculteurs ON recoltes.agriculteur_id = agriculteurs.id
           JOIN utilisateurs clients ON commandes.client_id = clients.id
           WHERE SUBSTR(commandes.date_creation, 1, 4) = ? AND commandes.statut IN ('livree', 'annulee')
           ORDER BY commandes.date_creation, commandes.id""", (annee,)
    ).fetchall()
    connexion_bd.close()
    return reponse_csv(
        f"ventes-{annee}.csv",
        ["N° commande", "Date", "Statut", "Produit", "Quantité", "Agriculteur", "Client", "Paiement",
         "Montant vente (FCFA)", "Frais livraison (FCFA)", "Commission (FCFA)", "Commission réglée",
         "Payée en ligne", "Encaissé en ligne (FCFA)", "Reversé à l'agriculteur", "Remboursé au client"],
        [[c["id"], c["jour"], c["statut"], c["produit"], c["quantite_demandee"], c["agriculteur"], c["client"],
          "Wave" if c["mode_paiement"] == "wave" else "à la livraison", c["montant"] or "",
          c["frais_livraison"] or "", c["commission"] or "", oui_non(c["commission_payee"]),
          oui_non(c["paye_en_ligne"]), c["montant_a_payer"] if c["paye_en_ligne"] else "",
          oui_non(c["reverse_agriculteur"]), oui_non(c["rembourse"])] for c in lignes],
    )


@app.route("/admin/export/premium.csv")
@admin_requis
def export_premium():
    annee = annee_demandee()
    connexion_bd = get_connexion()
    lignes = connexion_bd.execute(
        """SELECT paiements_premium.id, SUBSTR(paiements_premium.date_creation, 1, 10) AS jour,
                  utilisateurs.nom, utilisateurs.role, paiements_premium.reference, paiements_premium.montant,
                  paiements_premium.statut
           FROM paiements_premium JOIN utilisateurs ON paiements_premium.utilisateur_id = utilisateurs.id
           WHERE SUBSTR(paiements_premium.date_creation, 1, 4) = ?
           ORDER BY paiements_premium.date_creation, paiements_premium.id""", (annee,)
    ).fetchall()
    connexion_bd.close()
    return reponse_csv(
        f"premium-{annee}.csv",
        ["N°", "Date", "Membre", "Rôle", "Référence", "Montant (FCFA)", "Statut"],
        [[p["id"], p["jour"], p["nom"], p["role"], p["reference"], p["montant"], p["statut"]] for p in lignes],
    )
