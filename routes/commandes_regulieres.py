"""Commandes régulières : « 20 kg d'oignons chaque semaine ». Le client les crée en commandant,
les met en pause ou les arrête ; la tâche quotidienne (routes/taches.py) passe chaque commande
à sa date, et prévient le client si l'annonce n'est plus disponible ce jour-là."""
from datetime import date, timedelta

from flask import abort, flash, redirect, session, url_for

from database import get_connexion
from core import app, utilisateur_connecte
from stock import depasse_le_stock

FREQUENCES = {7: "chaque semaine", 14: "toutes les 2 semaines", 30: "chaque mois"}


def creer_reguliere(connexion_bd, client_id, recolte_id, quantite, frequence, mode_livraison,
                    adresse_livraison, mode_paiement):
    prochaine = (date.today() + timedelta(days=frequence)).isoformat()
    return connexion_bd.execute(
        """INSERT INTO commandes_regulieres (client_id, recolte_id, quantite, frequence_jours, mode_livraison,
                                             adresse_livraison, mode_paiement, prochaine_date)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING id""",
        (client_id, recolte_id, quantite, frequence, mode_livraison, adresse_livraison, mode_paiement, prochaine)
    ).fetchone()["id"]


def passer_commandes_du_jour(connexion_bd):
    """Crée les commandes régulières arrivées à échéance. Retourne les messages à envoyer
    (e-mail, téléphone, sujet, texte), comme les autres rappels quotidiens."""
    aujourdhui = date.today()
    messages = []
    for r in connexion_bd.execute(
        """SELECT commandes_regulieres.*, recoltes.nom, recoltes.statut, recoltes.masquee, recoltes.quantite AS stock,
                  clients.nom AS nom_client, clients.email AS email_client, clients.telephone AS telephone_client,
                  clients.suspendu, agriculteurs.nom AS nom_agriculteur, agriculteurs.email AS email_agriculteur,
                  agriculteurs.telephone AS telephone_agriculteur
           FROM commandes_regulieres
           JOIN recoltes ON commandes_regulieres.recolte_id = recoltes.id
           JOIN utilisateurs clients ON commandes_regulieres.client_id = clients.id
           JOIN utilisateurs agriculteurs ON recoltes.agriculteur_id = agriculteurs.id
           WHERE commandes_regulieres.actif = 1 AND commandes_regulieres.prochaine_date <= ?""",
        (aujourdhui.isoformat(),)
    ).fetchall():
        # Prochaine échéance : jamais dans le passé, même si des jours ont été manqués
        prochaine = date.fromisoformat(r["prochaine_date"])
        while prochaine <= aujourdhui:
            prochaine += timedelta(days=r["frequence_jours"])
        connexion_bd.execute("UPDATE commandes_regulieres SET prochaine_date = ? WHERE id = ?",
                             (prochaine.isoformat(), r["id"]))
        if r["suspendu"]:
            continue
        if r["statut"] != "disponible" or r["masquee"] or depasse_le_stock(r["stock"], r["quantite"]):
            messages.append((r["email_client"], r["telephone_client"], f"Commande régulière de {r['nom']} non passée",
                             f"Bonjour {r['nom_client']}, ta commande régulière de {r['quantite']} de {r['nom']} n'a pas "
                             f"pu être passée aujourd'hui : produit indisponible ou stock insuffisant. "
                             f"Nouvel essai le {prochaine.strftime('%d/%m/%Y')}."))
            continue
        connexion_bd.execute(
            """INSERT INTO commandes (recolte_id, client_id, quantite_demandee, message, mode_livraison,
                                     adresse_livraison, mode_paiement, reguliere_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (r["recolte_id"], r["client_id"], r["quantite"], f"Commande régulière ({FREQUENCES.get(r['frequence_jours'], '')})",
             r["mode_livraison"], r["adresse_livraison"], r["mode_paiement"], r["id"]))
        messages.append((r["email_agriculteur"], r["telephone_agriculteur"], f"Nouvelle commande régulière : {r['nom']}",
                         f"Bonjour {r['nom_agriculteur']}, {r['nom_client']} recommande {r['quantite']} de {r['nom']} "
                         f"(commande régulière). Confirme-la dans « Commandes reçues » sur App Agricole."))
        messages.append((r["email_client"], r["telephone_client"], f"Ta commande régulière de {r['nom']} est passée",
                         f"Bonjour {r['nom_client']}, ta commande régulière de {r['quantite']} de {r['nom']} a été "
                         f"envoyée à {r['nom_agriculteur']}. Prochaine le {prochaine.strftime('%d/%m/%Y')}."))
    connexion_bd.commit()
    return messages


@app.route("/commandes-regulieres/<int:reguliere_id>/<action>", methods=["POST"])
def gerer_reguliere(reguliere_id, action):
    if not utilisateur_connecte() or session["role"] != "client":
        return redirect(url_for("connexion"))
    requetes = {
        "pause": ("UPDATE commandes_regulieres SET actif = 0 WHERE id = ? AND client_id = ?", "Commande régulière en pause."),
        "reprendre": ("UPDATE commandes_regulieres SET actif = 1 WHERE id = ? AND client_id = ?", "Commande régulière reprise."),
        "arreter": ("DELETE FROM commandes_regulieres WHERE id = ? AND client_id = ?", "Commande régulière arrêtée."),
    }
    if action not in requetes:
        abort(404)
    requete, message = requetes[action]
    connexion_bd = get_connexion()
    if connexion_bd.execute(requete, (reguliere_id, session["utilisateur_id"])).rowcount:
        flash(message)
    connexion_bd.commit()
    connexion_bd.close()
    return redirect(url_for("mes_commandes"))
