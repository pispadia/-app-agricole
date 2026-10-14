"""Favoris (annonces gardées de côté) et agriculteurs suivis par un client."""
from flask import render_template, request, redirect, url_for, session, flash

from database import get_connexion, COLONNES_RECOLTE
from core import app, utilisateur_connecte
from routes.avis import NOTES_AGRICULTEURS

MAX_FAVORIS = 100
MAX_SUIVIS = 50


def est_client():
    return utilisateur_connecte() and session["role"] == "client"


def retour(recolte_id=None, agriculteur_id=None):
    """Revient sur la page d'où le client a cliqué (annonce, favoris ou page de l'agriculteur)."""
    page = request.form.get("retour")
    if page == "favoris":
        return redirect(url_for("mes_favoris"))
    if page == "agriculteur" and agriculteur_id:
        return redirect(url_for("avis_agriculteur", agriculteur_id=agriculteur_id))
    if recolte_id:
        return redirect(url_for("voir_annonce", recolte_id=recolte_id))
    return redirect(url_for("mes_favoris"))


def basculer(connexion_bd, table, colonne, valeur, maximum):
    """Ajoute la ligne si elle n'existe pas, la retire sinon. Renvoie True (ajoutée), False (retirée) ou None (plein)."""
    existe = connexion_bd.execute(
        f"SELECT id FROM {table} WHERE client_id = ? AND {colonne} = ?", (session["utilisateur_id"], valeur)
    ).fetchone()
    if existe:
        connexion_bd.execute(f"DELETE FROM {table} WHERE id = ?", (existe["id"],))
        connexion_bd.commit()
        return False
    nombre = connexion_bd.execute(
        f"SELECT COUNT(*) AS n FROM {table} WHERE client_id = ?", (session["utilisateur_id"],)).fetchone()["n"]
    if nombre >= maximum:
        return None
    connexion_bd.execute(f"INSERT INTO {table} (client_id, {colonne}) VALUES (?, ?)",
                         (session["utilisateur_id"], valeur))
    connexion_bd.commit()
    return True


@app.route("/annonce/<int:recolte_id>/favori", methods=["POST"])
def basculer_favori(recolte_id):
    if not est_client():
        return redirect(url_for("connexion"))
    connexion_bd = get_connexion()
    if connexion_bd.execute("SELECT id FROM recoltes WHERE id = ?", (recolte_id,)).fetchone() is None:
        connexion_bd.close()
        flash("Annonce introuvable.")
        return redirect(url_for("mes_favoris"))
    resultat = basculer(connexion_bd, "favoris", "recolte_id", recolte_id, MAX_FAVORIS)
    connexion_bd.close()
    if resultat is None:
        flash(f"Tu as déjà {MAX_FAVORIS} favoris : retires-en avant d'en ajouter.")
    else:
        flash("Annonce ajoutée à tes favoris ❤️" if resultat else "Annonce retirée de tes favoris.")
    return retour(recolte_id=recolte_id)


@app.route("/agriculteurs/<int:agriculteur_id>/suivre", methods=["POST"])
def suivre_agriculteur(agriculteur_id):
    if not est_client():
        return redirect(url_for("connexion"))
    recolte_id = request.form.get("recolte_id", type=int)
    connexion_bd = get_connexion()
    agriculteur = connexion_bd.execute(
        "SELECT nom FROM utilisateurs WHERE id = ? AND role = 'agriculteur'", (agriculteur_id,)).fetchone()
    if agriculteur is None:
        connexion_bd.close()
        flash("Agriculteur introuvable.")
        return redirect(url_for("mes_favoris"))
    resultat = basculer(connexion_bd, "agriculteurs_suivis", "agriculteur_id", agriculteur_id, MAX_SUIVIS)
    connexion_bd.close()
    if resultat is None:
        flash(f"Tu suis déjà {MAX_SUIVIS} agriculteurs : arrête d'en suivre un avant.")
    elif resultat:
        flash(f"Tu suis {agriculteur['nom']} : tu seras prévenu de ses nouvelles récoltes.")
    else:
        flash(f"Tu ne suis plus {agriculteur['nom']}.")
    return retour(recolte_id=recolte_id, agriculteur_id=agriculteur_id)


def etat_client(connexion_bd, recolte_id, agriculteur_id):
    """(annonce en favori ?, agriculteur suivi ?) pour le client connecté ; (False, False) sinon."""
    if not est_client():
        return False, False
    favori = connexion_bd.execute("SELECT id FROM favoris WHERE client_id = ? AND recolte_id = ?",
                                  (session["utilisateur_id"], recolte_id)).fetchone() is not None
    return favori, suit(connexion_bd, agriculteur_id)


def suit(connexion_bd, agriculteur_id):
    if not est_client():
        return False
    return connexion_bd.execute("SELECT id FROM agriculteurs_suivis WHERE client_id = ? AND agriculteur_id = ?",
                                (session["utilisateur_id"], agriculteur_id)).fetchone() is not None


@app.route("/mes-favoris")
def mes_favoris():
    if not est_client():
        return redirect(url_for("connexion"))
    connexion_bd = get_connexion()
    favoris = connexion_bd.execute(
        f"""SELECT {COLONNES_RECOLTE}, utilisateurs.nom AS nom_agriculteur
            FROM favoris
            JOIN recoltes ON favoris.recolte_id = recoltes.id
            JOIN utilisateurs ON recoltes.agriculteur_id = utilisateurs.id
            WHERE favoris.client_id = ? AND recoltes.masquee = 0 AND utilisateurs.suspendu = 0
            ORDER BY CASE WHEN recoltes.statut = 'disponible' THEN 0 ELSE 1 END, favoris.id DESC""",
        (session["utilisateur_id"],)
    ).fetchall()
    suivis = connexion_bd.execute(
        f"""SELECT utilisateurs.id, utilisateurs.nom, utilisateurs.verification,
                   notes.note_moyenne, notes.nb_avis,
                   (SELECT COUNT(*) FROM recoltes WHERE recoltes.agriculteur_id = utilisateurs.id
                       AND recoltes.statut = 'disponible' AND recoltes.masquee = 0) AS nb_annonces
            FROM agriculteurs_suivis
            JOIN utilisateurs ON agriculteurs_suivis.agriculteur_id = utilisateurs.id
            LEFT JOIN {NOTES_AGRICULTEURS} notes ON notes.agriculteur_id = utilisateurs.id
            WHERE agriculteurs_suivis.client_id = ? AND utilisateurs.suspendu = 0
            ORDER BY agriculteurs_suivis.id DESC""",
        (session["utilisateur_id"],)
    ).fetchall()
    connexion_bd.close()
    return render_template("mes_favoris.html", favoris=favoris, suivis=suivis)
