"""Contact et litiges : n'importe qui écrit à l'équipe (question, problème sur une commande,
paiement...) ; l'admin répond depuis /admin/support, la réponse part par e-mail et notification."""
import threading
from datetime import datetime

from flask import abort, flash, redirect, render_template, request, session, url_for
from markupsafe import escape

import push
from database import get_connexion
from core import app, EMAILS_ADMIN, limite_atteinte, utilisateur_connecte, utilisateur_courant
from emails import envoyer_email
from routes.premium import admin_requis

CATEGORIES = {
    "commande": "Problème sur une commande (non livrée, qualité, quantité...)",
    "paiement": "Paiement ou remboursement",
    "compte": "Mon compte",
    "annonce": "Une annonce ou un vendeur",
    "question": "Question ou suggestion",
}
LONGUEUR_MAX = 2000
MAX_DEMANDES_PAR_HEURE = 5


def commandes_de(connexion_bd, utilisateur_id):
    """Commandes que l'utilisateur peut citer : passées (client) ou reçues (agriculteur)."""
    return connexion_bd.execute(
        """SELECT commandes.id, commandes.statut, commandes.date_creation, recoltes.nom AS nom_recolte
           FROM commandes JOIN recoltes ON commandes.recolte_id = recoltes.id
           WHERE commandes.client_id = ? OR recoltes.agriculteur_id = ?
           ORDER BY commandes.date_creation DESC LIMIT 30""", (utilisateur_id, utilisateur_id)
    ).fetchall()


def prevenir_admins(demande_id, categorie, nom, message):
    lien = url_for("admin_support", _external=True)
    sujet = f"[App Agricole] Nouvelle demande n°{demande_id} : {CATEGORIES.get(categorie, categorie)}"
    contenu = (f"<p><strong>{escape(nom)}</strong> a écrit :</p><p>{escape(message)}</p>"
               f'<p><a href="{lien}">Répondre dans l\'administration</a></p>')

    def envoyer():
        for adresse in EMAILS_ADMIN:
            envoyer_email(adresse, sujet, contenu)
    threading.Thread(target=envoyer, daemon=True).start()


@app.route("/contact", methods=["GET", "POST"])
def contact():
    utilisateur = utilisateur_courant() if utilisateur_connecte() else None
    connexion_bd = get_connexion()
    commandes = commandes_de(connexion_bd, utilisateur["id"]) if utilisateur else []

    if request.method == "POST":
        categorie = request.form.get("categorie", "")
        message = request.form.get("message", "").strip()
        nom = utilisateur["nom"] if utilisateur else request.form.get("nom", "").strip()
        # Compte créé avec un téléphone : pas d'e-mail, la réponse est lue ici (et le numéro est gardé)
        email = (utilisateur["email"] or utilisateur["telephone"] or "") if utilisateur \
            else request.form.get("email", "").strip()
        commande_id = request.form.get("commande_id", "")
        commande_id = int(commande_id) if commande_id.isdigit() and int(commande_id) in {c["id"] for c in commandes} else None

        if categorie not in CATEGORIES or not message or not nom or (not utilisateur and "@" not in email):
            flash("Choisis un sujet et écris ton message (avec ton nom et ton e-mail).")
        elif len(message) > LONGUEUR_MAX:
            flash(f"Le message ne doit pas dépasser {LONGUEUR_MAX} caractères.")
        elif limite_atteinte(f"support:{request.remote_addr}", MAX_DEMANDES_PAR_HEURE, 3600):
            flash("Trop de messages envoyés. Réessaie dans une heure.")
        else:
            demande_id = connexion_bd.execute(
                """INSERT INTO demandes_support (utilisateur_id, nom, email, commande_id, categorie, message)
                   VALUES (?, ?, ?, ?, ?, ?) RETURNING id""",
                (utilisateur["id"] if utilisateur else None, nom[:100], email[:200], commande_id, categorie, message)
            ).fetchone()["id"]
            connexion_bd.commit()
            connexion_bd.close()
            prevenir_admins(demande_id, categorie, nom, message)
            flash(f"Message envoyé (demande n°{demande_id}). L'équipe te répond par e-mail"
                  f"{' et ici' if utilisateur else ''}, en général sous 48 h.")
            return redirect(url_for("contact"))

    demandes = connexion_bd.execute(
        "SELECT * FROM demandes_support WHERE utilisateur_id = ? ORDER BY date_creation DESC, id DESC",
        (utilisateur["id"],)
    ).fetchall() if utilisateur else []
    connexion_bd.close()
    commande_choisie = request.args.get("commande", "")
    return render_template("contact.html", categories=CATEGORIES, commandes=commandes, demandes=demandes,
                           utilisateur=utilisateur, saisie=request.form,
                           commande_choisie=int(commande_choisie) if commande_choisie.isdigit() else None)


@app.route("/admin/support")
@admin_requis
def admin_support():
    statut = "traitee" if request.args.get("statut") == "traitee" else "ouverte"
    connexion_bd = get_connexion()
    demandes = connexion_bd.execute(
        """SELECT demandes_support.*, recoltes.nom AS nom_recolte, commandes.statut AS statut_commande,
                  clients.nom AS nom_client, agriculteurs.nom AS nom_agriculteur
           FROM demandes_support
           LEFT JOIN commandes ON demandes_support.commande_id = commandes.id
           LEFT JOIN recoltes ON commandes.recolte_id = recoltes.id
           LEFT JOIN utilisateurs clients ON commandes.client_id = clients.id
           LEFT JOIN utilisateurs agriculteurs ON recoltes.agriculteur_id = agriculteurs.id
           WHERE demandes_support.statut = ?
           ORDER BY demandes_support.date_creation DESC, demandes_support.id DESC LIMIT 100""", (statut,)
    ).fetchall()
    connexion_bd.close()
    return render_template("admin_support.html", demandes=demandes, categories=CATEGORIES, statut=statut)


@app.route("/admin/support/<int:demande_id>/repondre", methods=["POST"])
@admin_requis
def repondre_support(demande_id):
    reponse = request.form.get("reponse", "").strip()
    connexion_bd = get_connexion()
    demande = connexion_bd.execute("SELECT * FROM demandes_support WHERE id = ?", (demande_id,)).fetchone()
    if demande is None:
        connexion_bd.close()
        abort(404)
    connexion_bd.execute(
        "UPDATE demandes_support SET statut = 'traitee', reponse = ?, date_reponse = ? WHERE id = ?",
        (reponse or None, datetime.now().strftime("%Y-%m-%d %H:%M"), demande_id))
    connexion_bd.commit()
    connexion_bd.close()
    if reponse and "@" in (demande["email"] or ""):  # sinon (compte par téléphone) : réponse lue dans l'app
        envoyer_email(demande["email"], f"Réponse à ta demande n°{demande_id} · App Agricole",
                      f"<p>Bonjour {escape(demande['nom'])},</p><p>{escape(reponse)}</p>"
                      f"<p>— L'équipe App Agricole</p><hr><p style=\"color:#888\">Ta demande : "
                      f"{escape(demande['message'])}</p>")
        if demande["utilisateur_id"]:
            push.alerter(demande["utilisateur_id"], None,
                         f"App Agricole : l'équipe a répondu à ta demande n°{demande_id}.", url_for("contact"))
        flash("Réponse envoyée.")
    else:
        flash("Demande classée sans réponse.")
    return redirect(url_for("admin_support"))
