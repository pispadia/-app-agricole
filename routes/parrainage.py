"""Parrainage : chaque utilisateur invite avec son lien ; quand un filleul réalise sa première
vraie vente ou son premier achat, le parrain reçoit un mois de Premium.

Garde-fous contre la fraude (faux comptes créés pour gagner du Premium) : la commande doit être
livrée, d'au moins MONTANT_MINIMUM FCFA, avec la commission réglée, et le parrain ne doit pas en
être l'acheteur ni le vendeur ; un parrain gagne au plus MAX_RECOMPENSES_PAR_AN mois par an."""
import secrets
from datetime import date
from urllib.parse import quote

from flask import render_template, redirect, url_for, session
from database import get_connexion
from core import app, utilisateur_connecte
from routes.premium import prolonger_premium
import sms

MONTANT_MINIMUM = 5000
MAX_RECOMPENSES_PAR_AN = 6
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sans 0/O ni 1/I, faciles à confondre


def code_de_parrainage(connexion_bd, utilisateur_id):
    """Le code de l'utilisateur, créé à la première demande."""
    ligne = connexion_bd.execute("SELECT code_parrainage FROM utilisateurs WHERE id = ?", (utilisateur_id,)).fetchone()
    if ligne["code_parrainage"]:
        return ligne["code_parrainage"]
    while True:
        code = "".join(secrets.choice(ALPHABET) for _ in range(8))
        if not connexion_bd.execute("SELECT 1 FROM utilisateurs WHERE code_parrainage = ?", (code,)).fetchone():
            break
    connexion_bd.execute("UPDATE utilisateurs SET code_parrainage = ? WHERE id = ?", (code, utilisateur_id))
    connexion_bd.commit()
    return code


def parrain_du_code(connexion_bd, code):
    if not code:
        return None
    ligne = connexion_bd.execute(
        "SELECT id FROM utilisateurs WHERE code_parrainage = ? AND suspendu = 0", (code.strip().upper(),)
    ).fetchone()
    return ligne["id"] if ligne else None


def recompenser_parrainage(connexion_bd, commande_id):
    """À appeler quand une commande est livrée ou que sa commission est réglée : récompense,
    une seule fois, le parrain du client et celui de l'agriculteur si les conditions sont remplies."""
    commande = connexion_bd.execute(
        """SELECT commandes.client_id, recoltes.agriculteur_id FROM commandes
           JOIN recoltes ON commandes.recolte_id = recoltes.id
           WHERE commandes.id = ? AND commandes.statut = 'livree' AND commandes.commission_payee = 1
             AND commandes.montant >= ?""",
        (commande_id, MONTANT_MINIMUM)
    ).fetchone()
    if commande is None:
        return
    parties = {commande["client_id"], commande["agriculteur_id"]}
    debut_annee = f"{date.today().year}-01-01"
    for filleul_id in parties:
        filleul = connexion_bd.execute(
            """SELECT filleul.nom, filleul.parrain_id, parrain.telephone AS telephone_parrain
               FROM utilisateurs filleul JOIN utilisateurs parrain ON filleul.parrain_id = parrain.id
               WHERE filleul.id = ? AND filleul.parrainage_recompense_le IS NULL AND parrain.suspendu = 0""",
            (filleul_id,)
        ).fetchone()
        if filleul is None or filleul["parrain_id"] in parties:
            continue
        deja_cette_annee = connexion_bd.execute(
            "SELECT COUNT(*) AS n FROM utilisateurs WHERE parrain_id = ? AND parrainage_recompense_le >= ?",
            (filleul["parrain_id"], debut_annee)
        ).fetchone()["n"]
        if deja_cette_annee >= MAX_RECOMPENSES_PAR_AN:
            continue
        # La mise à jour ne réussit qu'une fois, même si deux requêtes arrivent ensemble
        resultat = connexion_bd.execute(
            "UPDATE utilisateurs SET parrainage_recompense_le = ? WHERE id = ? AND parrainage_recompense_le IS NULL",
            (date.today().isoformat(), filleul_id)
        )
        if resultat.rowcount:
            fin = prolonger_premium(connexion_bd, filleul["parrain_id"])
            sms.alerter(filleul["telephone_parrain"],
                        f"App Agricole : merci ! {filleul['nom']}, que tu as invité, a fait sa première vente. "
                        f"Tu as 1 mois de Premium offert (jusqu'au {fin.strftime('%d/%m/%Y')}).")
    connexion_bd.commit()


@app.route("/parrainage")
def parrainage():
    if not utilisateur_connecte():
        return redirect(url_for("connexion"))
    connexion_bd = get_connexion()
    code = code_de_parrainage(connexion_bd, session["utilisateur_id"])
    filleuls = connexion_bd.execute(
        """SELECT nom, role, parrainage_recompense_le FROM utilisateurs
           WHERE parrain_id = ? ORDER BY id DESC""", (session["utilisateur_id"],)
    ).fetchall()
    connexion_bd.close()
    lien = url_for("inscription", parrain=code, _external=True)
    texte = ("Je vends et j'achète des récoltes sur App Agricole, au Sénégal. "
             f"Inscris-toi avec mon lien : {lien}")
    return render_template(
        "parrainage.html", code=code, lien=lien, filleuls=filleuls,
        lien_whatsapp="https://wa.me/?text=" + quote(texte),
        recompenses=sum(1 for f in filleuls if f["parrainage_recompense_le"]),
        montant_minimum=MONTANT_MINIMUM, maximum=MAX_RECOMPENSES_PAR_AN,
    )
