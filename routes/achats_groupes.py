"""Achats groupés : des clients s'associent pour atteindre la quantité minimum du prix de gros
d'une annonce (ex : 5 restaurants prennent ensemble 1 tonne d'oignons).

Un seul groupe ouvert par annonce, pendant 7 jours. Dès que le total des quantités atteint
l'objectif, une commande au prix de gros (prix convenu) est créée pour chaque participant et
l'agriculteur est prévenu. Sans objectif atteint à la date limite, le groupe expire (tâche
quotidienne) et les participants sont prévenus."""
import re
from datetime import date, timedelta

from flask import abort, render_template, request, redirect, url_for, session, flash

import push
from database import get_connexion
from core import app, utilisateur_connecte, quantite_valide
from stock import lire_quantite, ecrire_quantite, depasse_le_stock

DUREE_JOURS = 7
MAX_PARTICIPANTS = 30


def seuil_gros(texte):
    """« à partir de 500 kg » -> '500 kg' ; None si aucune quantité lisible."""
    trouve = re.search(r"\d+(?:[.,]\d+)?\s*[^\W\d_]+", texte or "")
    return trouve.group(0) if trouve and lire_quantite(trouve.group(0)) else None


def groupe_possible(recolte):
    """Objectif (texte) si l'annonce permet un achat groupé : prix de gros et quantité minimum lisible."""
    if not recolte["prix_gros"] or recolte["statut"] != "disponible" or recolte["masquee"]:
        return None
    return seuil_gros(recolte["quantite_gros_min"])


def total_groupe(connexion_bd, groupe):
    """(total, objectif) en valeurs comparables (kg ou unités)."""
    objectif = lire_quantite(groupe["objectif"])
    total = sum(lire_quantite(p["quantite"])[0] for p in connexion_bd.execute(
        "SELECT quantite FROM participations_groupe WHERE groupe_id = ?", (groupe["id"],)).fetchall())
    return total, objectif[0]


def groupe_ouvert(connexion_bd, recolte_id):
    return connexion_bd.execute(
        "SELECT * FROM achats_groupes WHERE recolte_id = ? AND statut = 'ouvert' AND date_limite >= ?",
        (recolte_id, date.today().isoformat())).fetchone()


def resume_groupe(connexion_bd, groupe):
    """Infos d'affichage : total, pourcentage, participants."""
    total, objectif = total_groupe(connexion_bd, groupe)
    participants = connexion_bd.execute(
        """SELECT participations_groupe.client_id, participations_groupe.quantite, utilisateurs.nom
           FROM participations_groupe JOIN utilisateurs ON participations_groupe.client_id = utilisateurs.id
           WHERE participations_groupe.groupe_id = ? ORDER BY participations_groupe.id""", (groupe["id"],)
    ).fetchall()
    return {
        "groupe": groupe, "participants": participants,
        "total": ecrire_quantite(total, groupe["objectif"]),
        "manque": ecrire_quantite(max(objectif - total, 0), groupe["objectif"]),
        "pourcent": min(int(total * 100 / objectif), 100) if objectif else 0,
    }


def quantite_participation(texte, groupe):
    """Quantité saisie, validée et dans la même unité que l'objectif, ou ValueError."""
    quantite = quantite_valide(texte)
    lue, objectif = lire_quantite(quantite), lire_quantite(groupe["objectif"])
    if not lue or lue[1] != objectif[1]:
        raise ValueError(f"Indique ta quantité dans la même unité que l'objectif ({groupe['objectif']}).")
    return quantite


def finaliser(connexion_bd, groupe, recolte):
    """Objectif atteint : une commande au prix de gros par participant, tout le monde est prévenu."""
    connexion_bd.execute("UPDATE achats_groupes SET statut = 'reussi' WHERE id = ?", (groupe["id"],))
    participants = connexion_bd.execute(
        """SELECT participations_groupe.client_id, participations_groupe.quantite, utilisateurs.telephone
           FROM participations_groupe JOIN utilisateurs ON participations_groupe.client_id = utilisateurs.id
           WHERE participations_groupe.groupe_id = ?""", (groupe["id"],)).fetchall()
    for participant in participants:
        connexion_bd.execute(
            """INSERT INTO commandes (recolte_id, client_id, quantite_demandee, message, prix_propose, negociation,
                                     achat_groupe_id)
               VALUES (?, ?, ?, ?, ?, 'acceptee', ?)""",
            (recolte["id"], participant["client_id"], participant["quantite"],
             f"Achat groupé n°{groupe['id']} ({groupe['objectif']} au total)", groupe["prix"], groupe["id"]))
    connexion_bd.commit()
    for participant in participants:
        push.alerter(participant["client_id"], participant["telephone"],
                     f"App Agricole : l'achat groupé de {recolte['nom']} a réussi ! Ta commande de "
                     f"{participant['quantite']} au prix de gros ({groupe['prix']}) est envoyée à l'agriculteur.",
                     url_for("mes_commandes"))
    agriculteur = connexion_bd.execute("SELECT id, telephone FROM utilisateurs WHERE id = ?",
                                       (recolte["agriculteur_id"],)).fetchone()
    push.alerter(agriculteur["id"], agriculteur["telephone"],
                 f"App Agricole : achat groupé de {recolte['nom']} réussi : {len(participants)} commandes "
                 f"({groupe['objectif']} au total) au prix de gros. Confirme-les.", url_for("commandes_recues"))


def rejoindre_ou_finaliser(connexion_bd, groupe, recolte, quantite, nouveau=False):
    """Enregistre la participation du client ; finalise si l'objectif est atteint. Renvoie un message."""
    ancienne = connexion_bd.execute(
        "SELECT quantite FROM participations_groupe WHERE groupe_id = ? AND client_id = ?",
        (groupe["id"], session["utilisateur_id"])).fetchone()
    total, objectif = total_groupe(connexion_bd, groupe)
    total_apres = total - (lire_quantite(ancienne["quantite"])[0] if ancienne else 0) + lire_quantite(quantite)[0]
    if depasse_le_stock(recolte["quantite"], ecrire_quantite(total_apres, groupe["objectif"])):
        raise ValueError(f"Il ne reste que {recolte['quantite']} : réduis ta quantité.")
    if ancienne:
        connexion_bd.execute("UPDATE participations_groupe SET quantite = ? WHERE groupe_id = ? AND client_id = ?",
                             (quantite, groupe["id"], session["utilisateur_id"]))
    else:
        nombre = connexion_bd.execute("SELECT COUNT(*) AS n FROM participations_groupe WHERE groupe_id = ?",
                                      (groupe["id"],)).fetchone()["n"]
        if nombre >= MAX_PARTICIPANTS:
            raise ValueError("Ce groupe est complet.")
        connexion_bd.execute("INSERT INTO participations_groupe (groupe_id, client_id, quantite) VALUES (?, ?, ?)",
                             (groupe["id"], session["utilisateur_id"], quantite))
    connexion_bd.commit()
    if total_apres >= objectif - 1e-9:
        finaliser(connexion_bd, groupe, recolte)
        return "🎉 Objectif atteint ! Les commandes au prix de gros sont envoyées à l'agriculteur."
    manque = ecrire_quantite(objectif - total_apres, groupe["objectif"])
    debut = "Achat groupé lancé" if nouveau else "Tu participes à l'achat groupé"
    return f"{debut} : il manque encore {manque}. Partage-le pour trouver d'autres acheteurs !"


def est_client():
    return utilisateur_connecte() and session["role"] == "client"


@app.route("/annonce/<int:recolte_id>/achat-groupe", methods=["POST"])
def lancer_achat_groupe(recolte_id):
    if not est_client():
        return redirect(url_for("connexion"))
    connexion_bd = get_connexion()
    recolte = connexion_bd.execute(
        """SELECT recoltes.* FROM recoltes JOIN utilisateurs ON recoltes.agriculteur_id = utilisateurs.id
           WHERE recoltes.id = ? AND utilisateurs.suspendu = 0""", (recolte_id,)).fetchone()
    objectif = groupe_possible(recolte) if recolte else None
    if not objectif:
        connexion_bd.close()
        flash("Cette annonce ne propose pas d'achat groupé.")
        return redirect(url_for("voir_annonce", recolte_id=recolte_id))

    groupe = groupe_ouvert(connexion_bd, recolte_id)
    nouveau = groupe is None
    if nouveau:
        groupe_id = connexion_bd.execute(
            """INSERT INTO achats_groupes (recolte_id, initiateur_id, objectif, prix, date_limite)
               VALUES (?, ?, ?, ?, ?) RETURNING id""",
            (recolte_id, session["utilisateur_id"], objectif, recolte["prix_gros"],
             (date.today() + timedelta(days=DUREE_JOURS)).isoformat())).fetchone()["id"]
        groupe = connexion_bd.execute("SELECT * FROM achats_groupes WHERE id = ?", (groupe_id,)).fetchone()
    try:
        message = rejoindre_ou_finaliser(connexion_bd, groupe, recolte,
                                         quantite_participation(request.form.get("quantite", ""), groupe), nouveau)
    except ValueError as erreur:
        if nouveau:  # groupe vide : on ne le garde pas
            connexion_bd.execute("DELETE FROM achats_groupes WHERE id = ?", (groupe["id"],))
            connexion_bd.commit()
        connexion_bd.close()
        flash(str(erreur))
        return redirect(url_for("voir_annonce", recolte_id=recolte_id))
    connexion_bd.close()
    flash(message)
    return redirect(url_for("voir_achat_groupe", groupe_id=groupe["id"]))


@app.route("/achats-groupes/<int:groupe_id>", methods=["GET", "POST"])
def voir_achat_groupe(groupe_id):
    connexion_bd = get_connexion()
    groupe = connexion_bd.execute("SELECT * FROM achats_groupes WHERE id = ?", (groupe_id,)).fetchone()
    if groupe is None:
        connexion_bd.close()
        abort(404)
    recolte = connexion_bd.execute(
        """SELECT recoltes.*, utilisateurs.nom AS nom_agriculteur FROM recoltes
           JOIN utilisateurs ON recoltes.agriculteur_id = utilisateurs.id WHERE recoltes.id = ?""",
        (groupe["recolte_id"],)).fetchone()
    ouvert = groupe["statut"] == "ouvert" and groupe["date_limite"] >= date.today().isoformat()

    if request.method == "POST":
        if not est_client():
            connexion_bd.close()
            return redirect(url_for("connexion"))
        if not ouvert or recolte["statut"] != "disponible":
            connexion_bd.close()
            flash("Cet achat groupé est terminé.")
            return redirect(url_for("voir_achat_groupe", groupe_id=groupe_id))
        if request.form.get("action") == "quitter":
            connexion_bd.execute("DELETE FROM participations_groupe WHERE groupe_id = ? AND client_id = ?",
                                 (groupe_id, session["utilisateur_id"]))
            connexion_bd.commit()
            flash("Tu ne participes plus à cet achat groupé.")
        else:
            try:
                flash(rejoindre_ou_finaliser(connexion_bd, groupe, recolte,
                                             quantite_participation(request.form.get("quantite", ""), groupe)))
            except ValueError as erreur:
                flash(str(erreur))
        connexion_bd.close()
        return redirect(url_for("voir_achat_groupe", groupe_id=groupe_id))

    resume = resume_groupe(connexion_bd, groupe)
    connexion_bd.close()
    role = session.get("role") if utilisateur_connecte() else None
    ma_part = next((p["quantite"] for p in resume["participants"]
                    if role == "client" and p["client_id"] == session["utilisateur_id"]), None)
    return render_template("achat_groupe.html", recolte=recolte, ouvert=ouvert, role=role, ma_part=ma_part,
                           lien=url_for("voir_achat_groupe", groupe_id=groupe_id, _external=True), **resume)


def expirer_groupes(connexion_bd):
    """Tâche quotidienne : groupes arrivés à la date limite sans objectif atteint. Renvoie les messages
    (email, téléphone, sujet, texte) pour les participants."""
    messages = []
    for groupe in connexion_bd.execute(
        """SELECT achats_groupes.id, recoltes.nom FROM achats_groupes
           JOIN recoltes ON achats_groupes.recolte_id = recoltes.id
           WHERE achats_groupes.statut = 'ouvert' AND achats_groupes.date_limite < ?""",
        (date.today().isoformat(),)).fetchall():
        connexion_bd.execute("UPDATE achats_groupes SET statut = 'expire' WHERE id = ?", (groupe["id"],))
        for participant in connexion_bd.execute(
            """SELECT utilisateurs.nom, utilisateurs.email, utilisateurs.telephone FROM participations_groupe
               JOIN utilisateurs ON participations_groupe.client_id = utilisateurs.id
               WHERE participations_groupe.groupe_id = ?""", (groupe["id"],)).fetchall():
            messages.append((participant["email"], participant["telephone"],
                             f"Achat groupé de {groupe['nom']} non abouti",
                             f"Bonjour {participant['nom']}, l'achat groupé de {groupe['nom']} n'a pas atteint "
                             f"la quantité du prix de gros à temps : aucune commande n'a été passée. Tu peux "
                             f"commander au prix normal ou relancer un achat groupé sur l'annonce."))
    connexion_bd.commit()
    return messages
