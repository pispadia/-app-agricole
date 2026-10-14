"""Promotions : l'agriculteur baisse le prix d'une annonce de 10 à 50 % pendant quelques jours.

Le prix est un texte libre (« 500 FCFA / kg ») : on applique la réduction au premier montant, le
reste (unité) ne change pas. Le prix promo est retenu sur la commande au moment où elle est passée."""
import re
from datetime import date, timedelta

from core import app

POURCENTAGES = (10, 15, 20, 25, 30, 40, 50)
DUREES_JOURS = (3, 7, 14)


def promo_active(recolte):
    """Pourcentage de réduction en cours sur cette annonce, ou 0."""
    try:
        pourcent, fin = recolte["promo_pourcent"], recolte["promo_jusqu_au"]
    except (KeyError, IndexError):
        return 0
    if pourcent and fin and fin >= date.today().isoformat():
        return pourcent
    return 0


def prix_reduit(prix, pourcent):
    """'500 FCFA / kg', 20 -> '400 FCFA / kg' (arrondi à 5 FCFA dès 100, espaces des milliers gardés)."""
    trouve = re.match(r"(\s*)(\d[\d ]*\d|\d)", prix or "")
    if not trouve or not pourcent:
        return prix
    valeur = int(trouve.group(2).replace(" ", ""))
    pas = 5 if valeur >= 100 else 1
    nouveau = max(int(round(valeur * (100 - pourcent) / 100 / pas)) * pas, 1)
    texte = f"{nouveau:,}".replace(",", " ") if " " in trouve.group(2) else str(nouveau)
    return trouve.group(1) + texte + prix[trouve.end():]


def prix_promo(recolte):
    """Prix réduit si une promotion est en cours, sinon None."""
    pourcent = promo_active(recolte)
    return prix_reduit(recolte["prix"], pourcent) if pourcent else None


def fin_promo(duree_jours):
    return (date.today() + timedelta(days=duree_jours)).isoformat()


app.add_template_global(promo_active)
app.add_template_global(prix_promo)
