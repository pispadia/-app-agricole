"""Mode très simple de l'espace agriculteur : quelques gros boutons avec des images, et chaque texte
peut être lu à voix haute (synthèse vocale du téléphone), pour ceux qui lisent peu.

Le choix est gardé sur le compte : l'espace agriculteur s'ouvre ensuite directement dans ce mode."""
from datetime import date

from flask import render_template, request, redirect, url_for, session

from database import get_connexion
from core import app, utilisateur_connecte


def mode_simple_actif(connexion_bd, utilisateur_id):
    ligne = connexion_bd.execute("SELECT mode_simple FROM utilisateurs WHERE id = ?", (utilisateur_id,)).fetchone()
    return bool(ligne and ligne["mode_simple"])


def chiffres_simples(connexion_bd, agriculteur_id):
    """Commandes à confirmer, ventes livrées du mois et depuis le début, annonces en ligne."""
    mois = date.today().strftime("%Y-%m")
    ligne = connexion_bd.execute(
        """SELECT SUM(CASE WHEN commandes.statut = 'en_attente' THEN 1 ELSE 0 END) AS a_confirmer,
                  SUM(CASE WHEN commandes.statut = 'confirmee' THEN 1 ELSE 0 END) AS a_livrer,
                  COALESCE(SUM(CASE WHEN commandes.statut = 'livree' AND SUBSTR(commandes.date_creation, 1, 7) = ?
                                    THEN commandes.montant END), 0) AS ventes_mois,
                  COALESCE(SUM(CASE WHEN commandes.statut = 'livree' THEN commandes.montant END), 0) AS ventes_total
           FROM commandes JOIN recoltes ON commandes.recolte_id = recoltes.id
           WHERE recoltes.agriculteur_id = ?""", (mois, agriculteur_id)).fetchone()
    en_ligne = connexion_bd.execute(
        "SELECT COUNT(*) AS n FROM recoltes WHERE agriculteur_id = ? AND statut = 'disponible' AND masquee = 0",
        (agriculteur_id,)).fetchone()["n"]
    return {"a_confirmer": ligne["a_confirmer"] or 0, "a_livrer": ligne["a_livrer"] or 0,
            "ventes_mois": int(ligne["ventes_mois"] or 0), "ventes_total": int(ligne["ventes_total"] or 0),
            "en_ligne": en_ligne}


def espace_simple():
    """Page d'accueil de l'agriculteur en mode très simple (appelée par espace_agriculteur)."""
    connexion_bd = get_connexion()
    chiffres = chiffres_simples(connexion_bd, session["utilisateur_id"])
    connexion_bd.close()
    return render_template("espace_simple.html", prenom=session["nom"].split(" ")[0], **chiffres)


@app.route("/espace-agriculteur/mode-simple", methods=["POST"])
def changer_mode_simple():
    if not utilisateur_connecte() or session["role"] != "agriculteur":
        return redirect(url_for("connexion"))
    actif = 1 if request.form.get("actif") == "1" else 0
    connexion_bd = get_connexion()
    connexion_bd.execute("UPDATE utilisateurs SET mode_simple = ? WHERE id = ?", (actif, session["utilisateur_id"]))
    connexion_bd.commit()
    connexion_bd.close()
    return redirect(url_for("espace_agriculteur"))
