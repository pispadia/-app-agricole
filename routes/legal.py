"""Pages légales : conditions générales d'utilisation et politique de confidentialité."""
import os

from flask import render_template
from core import app, TAUX_COMMISSION, PRIX_PREMIUM_MENSUEL, DUREE_PREMIUM_JOURS

MISE_A_JOUR = "14 octobre 2026"


def infos_legales():
    return {
        "mise_a_jour": MISE_A_JOUR,
        # Adresse de contact affichée : EMAIL_CONTACT, sinon l'adresse d'envoi des e-mails
        "email_contact": os.environ.get("EMAIL_CONTACT") or os.environ.get("EMAIL_EXPEDITEUR") or "",
        "editeur": os.environ.get("EDITEUR_NOM", ""),
        "taux_commission": round(TAUX_COMMISSION * 100, 1),
        "prix_premium": PRIX_PREMIUM_MENSUEL,
        "duree_premium": DUREE_PREMIUM_JOURS,
    }


@app.route("/conditions")
def conditions():
    return render_template("legal/conditions.html", **infos_legales())


@app.route("/confidentialite")
def confidentialite():
    return render_template("legal/confidentialite.html", **infos_legales())
