"""Coordonnées des localités du Sénégal, pour placer les annonces sur la carte.

La localité d'une annonce est un texte libre (« Thiès », « Potou, Louga »...) : on cherche
le premier lieu connu qu'il contient. Coordonnées approximatives (centre de la ville ou de
la zone), suffisantes pour une carte à l'échelle du pays.
"""
import re

from prix_marche import sans_accents

LIEUX = {
    # Dakar
    "dakar": (14.716, -17.467), "pikine": (14.755, -17.390), "guediawaye": (14.776, -17.394),
    "rufisque": (14.716, -17.273), "keur massar": (14.783, -17.317), "sangalkam": (14.783, -17.217),
    "diamniadio": (14.722, -17.183), "bayakh": (14.917, -17.117), "sebikotane": (14.744, -17.136),
    # Thiès et les Niayes
    "thies": (14.791, -16.926), "mbour": (14.420, -16.960), "tivaouane": (14.950, -16.817),
    "joal": (14.167, -16.833), "mboro": (15.150, -16.883), "pout": (14.770, -17.060),
    "khombole": (14.767, -16.700), "niayes": (15.000, -16.950), "kayar": (14.917, -17.117),
    "notto": (14.950, -17.050), "fandene": (14.800, -16.880),
    # Louga
    "louga": (15.619, -16.224), "potou": (15.720, -16.500), "kebemer": (15.370, -16.440),
    "linguere": (15.395, -15.117), "ndande": (15.310, -16.470), "dahra": (15.348, -15.480),
    # Saint-Louis et la vallée du fleuve
    "saint louis": (16.030, -16.489), "richard toll": (16.462, -15.700), "dagana": (16.517, -15.500),
    "podor": (16.652, -14.959), "ross bethio": (16.270, -16.140), "ndioum": (16.513, -14.647),
    "rosso": (16.500, -15.810),
    # Matam
    "matam": (15.656, -13.256), "ourossogui": (15.605, -13.322), "kanel": (15.492, -13.176),
    # Diourbel
    "diourbel": (14.655, -16.234), "touba": (14.850, -15.883), "mbacke": (14.790, -15.908),
    "bambey": (14.700, -16.450),
    # Fatick, Kaolack, Kaffrine
    "fatick": (14.339, -16.411), "foundiougne": (14.133, -16.467), "sokone": (13.883, -16.367),
    "gossas": (14.493, -16.066), "kaolack": (14.152, -16.073), "nioro": (13.750, -15.783),
    "guinguineo": (14.267, -15.950), "kaffrine": (14.106, -15.550), "koungheul": (13.983, -14.800),
    "birkelane": (14.133, -15.750),
    # Est et Sud
    "tambacounda": (13.771, -13.668), "koumpentoum": (13.983, -14.550), "goudiry": (14.183, -12.717),
    "bakel": (14.900, -12.458), "kedougou": (12.557, -12.174), "kolda": (12.883, -14.950),
    "velingara": (13.150, -14.117), "sedhiou": (12.708, -15.557), "ziguinchor": (12.583, -16.272),
    "bignona": (12.810, -16.226), "oussouye": (12.485, -16.547), "cap skirring": (12.390, -16.746),
    "casamance": (12.700, -15.800),
}
# Autres façons d'écrire les mêmes lieux
ALIAS = {"st louis": "saint louis", "tamba": "tambacounda", "richard tol": "richard toll"}


def normaliser(texte):
    return " ".join(re.findall(r"[a-z]+", sans_accents(texte or "").lower()))


def coordonnees(localite):
    """(latitude, longitude) du premier lieu connu cité dans la localité, ou None."""
    texte = f" {normaliser(localite)} "
    for alias, lieu in ALIAS.items():
        texte = texte.replace(f" {alias} ", f" {lieu} ")
    # Le premier lieu cité (« Potou, Louga » -> Potou) ; à position égale, le nom le plus long
    trouves = [(texte.find(f" {lieu} "), -len(lieu), lieu) for lieu in LIEUX if f" {lieu} " in texte]
    return LIEUX[min(trouves)[2]] if trouves else None
