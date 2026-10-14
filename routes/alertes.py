"""Alertes produits : « préviens-moi quand il y a du mil à Thiès »."""
import threading

from flask import render_template, request, redirect, url_for, session, flash
from markupsafe import escape

import sms
from database import get_connexion
from core import app, utilisateur_connecte
from emails import envoyer_email
from prix_marche import produit_cle, sans_accents

MAX_ALERTES = 10


def meme_localite(localite_alerte, localite_recolte):
    """Sans localité, l'alerte vaut partout ; sinon « thies » correspond à « Thiès (Mbour) »."""
    if not localite_alerte:
        return True
    return sans_accents(localite_alerte).lower().strip() in sans_accents(localite_recolte or "").lower()


@app.route("/mes-alertes", methods=["GET", "POST"])
def mes_alertes():
    if not utilisateur_connecte() or session["role"] != "client":
        return redirect(url_for("connexion"))

    connexion_bd = get_connexion()
    if request.method == "POST":
        libelle = " ".join(request.form.get("produit", "").split())[:60]
        localite = " ".join(request.form.get("localite", "").split())[:60] or None
        produit = produit_cle(libelle)
        nombre = connexion_bd.execute(
            "SELECT COUNT(*) AS n FROM alertes_produit WHERE client_id = ?", (session["utilisateur_id"],)
        ).fetchone()["n"]
        if not produit:
            flash("Indique le produit recherché (ex: mil, oignon).")
        elif nombre >= MAX_ALERTES:
            flash(f"Tu as déjà {MAX_ALERTES} alertes : supprimes-en une avant d'en créer une autre.")
        else:
            connexion_bd.execute(
                "INSERT INTO alertes_produit (client_id, produit, libelle, localite) VALUES (?, ?, ?, ?)",
                (session["utilisateur_id"], produit, libelle, localite)
            )
            connexion_bd.commit()
            flash(f"Alerte créée : tu seras prévenu dès qu'une annonce de « {libelle} » sera publiée"
                  + (f" à {localite}." if localite else "."))
        connexion_bd.close()
        return redirect(url_for("mes_alertes"))

    alertes = connexion_bd.execute(
        "SELECT * FROM alertes_produit WHERE client_id = ? ORDER BY id DESC", (session["utilisateur_id"],)
    ).fetchall()
    connexion_bd.close()
    return render_template("mes_alertes.html", alertes=alertes, maximum=MAX_ALERTES)


@app.route("/mes-alertes/<int:alerte_id>/supprimer", methods=["POST"])
def supprimer_alerte(alerte_id):
    if not utilisateur_connecte() or session["role"] != "client":
        return redirect(url_for("connexion"))
    connexion_bd = get_connexion()
    connexion_bd.execute("DELETE FROM alertes_produit WHERE id = ? AND client_id = ?",
                         (alerte_id, session["utilisateur_id"]))
    connexion_bd.commit()
    connexion_bd.close()
    flash("Alerte supprimée.")
    return redirect(url_for("mes_alertes"))


def prevenir_clients(connexion_bd, recolte_id, nom, localite, prix):
    """Après la publication d'une récolte : prévient (e-mail + SMS) les clients dont une alerte correspond.
    Les envois partent en arrière-plan pour ne pas faire attendre l'agriculteur."""
    produit = produit_cle(nom)
    if not produit:
        return
    clients = {}
    for alerte in connexion_bd.execute(
        """SELECT alertes_produit.localite, utilisateurs.id, utilisateurs.nom, utilisateurs.email,
                  utilisateurs.telephone
           FROM alertes_produit JOIN utilisateurs ON alertes_produit.client_id = utilisateurs.id
           WHERE alertes_produit.produit = ? AND utilisateurs.suspendu = 0""",
        (produit,)
    ).fetchall():
        if meme_localite(alerte["localite"], localite):
            clients[alerte["id"]] = alerte  # un seul message par client, même s'il a plusieurs alertes

    if not clients:
        return
    lien = url_for("voir_annonce", recolte_id=recolte_id, _external=True)

    def envoyer():
        for client in clients.values():
            envoyer_email(
                client["email"], f"Nouvelle annonce : {nom} à {localite}",
                f"<p>Bonjour {escape(client['nom'])},</p>"
                f"<p>Une récolte qui correspond à ton alerte vient d'être publiée : "
                f"<strong>{escape(nom)}</strong> à {escape(localite)}, {escape(prix)}.</p>"
                f'<p><a href="{lien}">Voir l\'annonce et commander</a></p>'
                f"<p>Tu peux gérer tes alertes dans « Mes alertes » sur App Agricole.</p>",
            )
            sms.alerter(client["telephone"], f"App Agricole : {nom} disponible à {localite} ({prix}). {lien}")

    threading.Thread(target=envoyer, daemon=True).start()
