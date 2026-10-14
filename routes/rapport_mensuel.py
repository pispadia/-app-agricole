"""Rapport mensuel de l'agriculteur : ventes du mois passé, produits les plus demandés, avis reçus,
nouveaux abonnés et conseil de prix par rapport au marché.

Visible à tout moment dans son espace (/espace-agriculteur/rapport) et envoyé par e-mail au début
de chaque mois par la tâche quotidienne (routes/taches.py), une seule fois par mois et par agriculteur,
seulement s'il a eu de l'activité. L'agriculteur peut désactiver l'e-mail."""
from datetime import date, timedelta

from flask import render_template, request, redirect, url_for, session, flash

from database import get_connexion
from core import app, utilisateur_connecte
from prix_marche import prix_au_kg, prix_du_marche, produit_cle

MOIS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
        "novembre", "décembre")
MAX_RAPPORTS_PAR_JOUR = 150  # quota d'e-mails gratuits : le reste part les jours suivants
ECART_CONSEIL = 15  # écart au prix médian (en %) à partir duquel on donne un conseil


def mois_precedent(aujourdhui=None):
    """'2026-10-14' -> '2026-09'."""
    premier = (aujourdhui or date.today()).replace(day=1)
    return (premier - timedelta(days=1)).strftime("%Y-%m")


def libelle_mois(mois):
    annee, numero = mois.split("-")
    return f"{MOIS[int(numero) - 1]} {annee}"


def conseils_prix(connexion_bd, agriculteur_id):
    """Pour chaque annonce en ligne : écart de son prix au kg avec le prix médian du marché."""
    marche = prix_du_marche(connexion_bd)
    conseils = []
    for recolte in connexion_bd.execute(
        "SELECT nom, prix FROM recoltes WHERE agriculteur_id = ? AND statut = 'disponible' AND masquee = 0",
        (agriculteur_id,)
    ).fetchall():
        reference, prix = marche.get(produit_cle(recolte["nom"])), prix_au_kg(recolte["prix"])
        if not reference or not prix:
            continue
        ecart = round((prix - reference["median"]) * 100 / reference["median"])
        if ecart >= ECART_CONSEIL:
            texte = (f"{recolte['nom']} : ton prix ({recolte['prix']}) est {ecart} % au-dessus du prix courant "
                     f"({reference['median']} FCFA/kg). Une baisse ou une promo peut t'aider à vendre plus vite.")
        elif ecart <= -ECART_CONSEIL:
            texte = (f"{recolte['nom']} : ton prix ({recolte['prix']}) est {-ecart} % en dessous du prix courant "
                     f"({reference['median']} FCFA/kg). Tu peux sans doute le monter un peu.")
        else:
            continue
        conseils.append(texte)
    return conseils


def rapport(connexion_bd, agriculteur_id, mois):
    """Chiffres du mois 'AAAA-MM' pour un agriculteur."""
    commandes = connexion_bd.execute(
        """SELECT COUNT(*) AS recues,
                  SUM(CASE WHEN commandes.statut = 'livree' THEN 1 ELSE 0 END) AS livrees,
                  SUM(CASE WHEN commandes.statut = 'livree' THEN COALESCE(commandes.montant, 0) ELSE 0 END) AS ventes
           FROM commandes JOIN recoltes ON commandes.recolte_id = recoltes.id
           WHERE recoltes.agriculteur_id = ? AND SUBSTR(commandes.date_creation, 1, 7) = ?""",
        (agriculteur_id, mois)
    ).fetchone()
    produits = connexion_bd.execute(
        """SELECT recoltes.nom, COUNT(*) AS n FROM commandes JOIN recoltes ON commandes.recolte_id = recoltes.id
           WHERE recoltes.agriculteur_id = ? AND SUBSTR(commandes.date_creation, 1, 7) = ?
           GROUP BY recoltes.nom ORDER BY n DESC, recoltes.nom LIMIT 3""",
        (agriculteur_id, mois)
    ).fetchall()
    avis = connexion_bd.execute(
        """SELECT COUNT(*) AS n, AVG(note) AS moyenne FROM avis
           WHERE agriculteur_id = ? AND SUBSTR(date_creation, 1, 7) = ?""",
        (agriculteur_id, mois)
    ).fetchone()
    abonnes = connexion_bd.execute(
        """SELECT COUNT(*) AS n FROM agriculteurs_suivis
           WHERE agriculteur_id = ? AND SUBSTR(date_creation, 1, 7) = ?""",
        (agriculteur_id, mois)
    ).fetchone()["n"]
    publiees = connexion_bd.execute(
        "SELECT COUNT(*) AS n FROM recoltes WHERE agriculteur_id = ? AND SUBSTR(date_creation, 1, 7) = ?",
        (agriculteur_id, mois)
    ).fetchone()["n"]
    return {
        "mois": mois, "libelle": libelle_mois(mois),
        "recues": commandes["recues"] or 0, "livrees": commandes["livrees"] or 0, "ventes": commandes["ventes"] or 0,
        "produits": [(p["nom"], p["n"]) for p in produits],
        "nb_avis": avis["n"] or 0, "note_avis": round(avis["moyenne"], 1) if avis["moyenne"] else None,
        "abonnes": abonnes, "publiees": publiees,
        "conseils": conseils_prix(connexion_bd, agriculteur_id),
    }


def a_de_l_activite(chiffres):
    return any(chiffres[cle] for cle in ("recues", "nb_avis", "abonnes", "publiees"))


def montant(valeur):
    return f"{int(valeur):,}".replace(",", " ")


def html_rapport(nom, chiffres, lien):
    """Corps de l'e-mail (HTML simple, lisible dans toutes les messageries)."""
    from markupsafe import escape
    lignes = [
        f"<p>Bonjour {escape(nom)},</p>",
        f"<p>Voici ton bilan de <strong>{chiffres['libelle']}</strong> sur App Agricole :</p>",
        "<ul>",
        f"<li>📦 {chiffres['recues']} commande(s) reçue(s), {chiffres['livrees']} livrée(s)</li>",
        f"<li>💰 {montant(chiffres['ventes'])} FCFA de ventes livrées</li>",
        f"<li>🌾 {chiffres['publiees']} annonce(s) publiée(s)</li>",
    ]
    if chiffres["nb_avis"]:
        lignes.append(f"<li>⭐ {chiffres['nb_avis']} nouvel(s) avis, note moyenne {chiffres['note_avis']}/5</li>")
    if chiffres["abonnes"]:
        lignes.append(f"<li>➕ {chiffres['abonnes']} nouveau(x) client(s) te suivent</li>")
    lignes.append("</ul>")
    if chiffres["produits"]:
        lignes.append("<p><strong>Tes produits les plus demandés :</strong> "
                      + ", ".join(f"{escape(nom_p)} ({n})" for nom_p, n in chiffres["produits"]) + "</p>")
    if chiffres["conseils"]:
        lignes.append("<p><strong>Conseils prix :</strong></p><ul>"
                      + "".join(f"<li>{escape(c)}</li>" for c in chiffres["conseils"]) + "</ul>")
    lignes.append(f'<p><a href="{lien}">Voir mon rapport sur App Agricole</a> (tu peux aussi y désactiver cet e-mail).</p>')
    return "".join(lignes)


def preparer_rapports(connexion_bd, aujourdhui=None):
    """Rapports du mois précédent pas encore envoyés : [(email, sujet, html)], marqués comme envoyés.
    Les agriculteurs sans activité sont marqués sans recevoir d'e-mail."""
    mois = mois_precedent(aujourdhui)
    lien = url_for("rapport_mensuel", _external=True)
    envois = []
    for agriculteur in connexion_bd.execute(
        """SELECT id, nom, email FROM utilisateurs
           WHERE role = 'agriculteur' AND suspendu = 0 AND rapport_mensuel = 1
             AND (rapport_envoye_pour IS NULL OR rapport_envoye_pour < ?)
           ORDER BY id""",
        (mois,)
    ).fetchall():
        if len(envois) >= MAX_RAPPORTS_PAR_JOUR:
            break
        chiffres = rapport(connexion_bd, agriculteur["id"], mois)
        connexion_bd.execute("UPDATE utilisateurs SET rapport_envoye_pour = ? WHERE id = ?", (mois, agriculteur["id"]))
        if a_de_l_activite(chiffres):
            envois.append((agriculteur["email"], f"Ton bilan de {chiffres['libelle']} sur App Agricole",
                           html_rapport(agriculteur["nom"], chiffres, lien)))
    connexion_bd.commit()
    return envois


@app.route("/espace-agriculteur/rapport", methods=["GET", "POST"])
def rapport_mensuel():
    if not utilisateur_connecte() or session["role"] != "agriculteur":
        return redirect(url_for("connexion"))
    connexion_bd = get_connexion()
    if request.method == "POST":
        actif = 1 if request.form.get("rapport_mensuel") else 0
        connexion_bd.execute("UPDATE utilisateurs SET rapport_mensuel = ? WHERE id = ?",
                             (actif, session["utilisateur_id"]))
        connexion_bd.commit()
        connexion_bd.close()
        flash("Tu recevras ce bilan par e-mail chaque début de mois." if actif
              else "Tu ne recevras plus ce bilan par e-mail.")
        return redirect(url_for("rapport_mensuel"))

    choisi = request.args.get("mois", "")
    mois_courant = date.today().strftime("%Y-%m")
    mois = choisi if len(choisi) == 7 and choisi[4] == "-" and choisi[:4].isdigit() and choisi[5:].isdigit() \
        and 1 <= int(choisi[5:]) <= 12 and choisi <= mois_courant else mois_precedent()
    chiffres = rapport(connexion_bd, session["utilisateur_id"], mois)
    actif = connexion_bd.execute("SELECT rapport_mensuel FROM utilisateurs WHERE id = ?",
                                 (session["utilisateur_id"],)).fetchone()["rapport_mensuel"]
    connexion_bd.close()
    # Les 6 derniers mois pour naviguer
    choix, premier = [], date.today().replace(day=1)
    for _ in range(6):
        choix.append(premier.strftime("%Y-%m"))
        premier = (premier - timedelta(days=1)).replace(day=1)
    return render_template("rapport_mensuel.html", chiffres=chiffres, actif=actif,
                           choix_mois=[(m, libelle_mois(m)) for m in choix], montant=montant)
