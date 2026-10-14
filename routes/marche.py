"""Page « Prix du marché »."""
from flask import render_template
from database import get_connexion
from core import app
from prix_marche import prix_du_marche, PERIODE_JOURS


@app.route("/prix-du-marche")
def prix_marche():
    connexion_bd = get_connexion()
    produits = prix_du_marche(connexion_bd)
    connexion_bd.close()
    return render_template("prix_marche.html", produits=produits.values(), periode=PERIODE_JOURS)
