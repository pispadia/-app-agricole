"""Prix du marché : prix courant au kilo de chaque produit, calculé à partir des annonces.

Les prix sont saisis en texte libre ("500 FCFA / kg", "450000 F / tonne") ; seules les
annonces dont le prix est exprimé au kilo ou à la tonne sont prises en compte.
"""
import re
import unicodedata
from datetime import date, timedelta
from statistics import median

PERIODE_JOURS = 180   # annonces des 6 derniers mois
MINIMUM_ANNONCES = 2  # en dessous, un « prix du marché » n'aurait pas de sens
MOTS_IGNORES = {"de", "du", "des", "la", "le", "les", "en", "bio"}


def sans_accents(texte):
    return "".join(c for c in unicodedata.normalize("NFD", texte) if unicodedata.category(c) != "Mn")


def produit_cle(nom):
    """'Oignons violets de Galmi' -> 'oignon' : le premier mot significatif, au singulier."""
    for mot in re.findall(r"[a-z]+", sans_accents(nom or "").lower()):
        if mot in MOTS_IGNORES:
            continue
        if len(mot) > 4 and mot.endswith("s") and not mot.endswith(("is", "us", "ss")):
            mot = mot[:-1]
        return mot
    return None


def nom_affiche(nom):
    """Le mot du produit tel que saisi, accents compris ('Maïs jaune' -> 'Maïs')."""
    for mot in re.findall(r"[^\W\d_]+", nom or ""):
        if sans_accents(mot).lower() not in MOTS_IGNORES:
            return mot.capitalize()
    return ""


def prix_au_kg(prix):
    """'500 FCFA / kg' -> 500 ; '450 000 F / tonne' -> 450 ; None si l'unité n'est pas un poids."""
    texte = sans_accents(prix or "").lower()
    nombre = re.match(r"\s*(\d[\d ]*(?:[.,]\d+)?)", texte)
    unite = re.search(r"/\s*([a-z]+)", texte)
    if not nombre or not unite:
        return None
    valeur = float(nombre.group(1).replace(" ", "").replace(",", "."))
    unite = unite.group(1)
    if unite in ("kg", "kilo", "kilos", "kilogramme", "kilogrammes"):
        return valeur
    if unite in ("t", "tonne", "tonnes"):
        return valeur / 1000
    return None


def prix_du_marche(connexion_bd):
    """{produit: {"nom", "median", "min", "max", "nombre"}} pour les produits assez représentés."""
    depuis = (date.today() - timedelta(days=PERIODE_JOURS)).isoformat()
    annonces = connexion_bd.execute(
        "SELECT nom, prix FROM recoltes WHERE date_creation >= ?", (depuis,)
    ).fetchall()

    prix_par_produit, noms = {}, {}
    for annonce in annonces:
        cle, prix = produit_cle(annonce["nom"]), prix_au_kg(annonce["prix"])
        if cle and prix:
            prix_par_produit.setdefault(cle, []).append(prix)
            noms.setdefault(cle, nom_affiche(annonce["nom"]))

    return {
        cle: {"nom": noms[cle], "median": round(median(prix)), "min": round(min(prix)),
              "max": round(max(prix)), "nombre": len(prix)}
        for cle, prix in sorted(prix_par_produit.items())
        if len(prix) >= MINIMUM_ANNONCES
    }
