"""Météo agricole des 7 prochains jours via Open-Meteo (gratuit, sans clé, https://open-meteo.com).

Les prévisions sont gardées 3 heures en mémoire par lieu, pour ne pas ralentir les pages ni
interroger le service à chaque visite. En cas de panne, on n'affiche simplement pas de météo."""
import json
import threading
import time
import urllib.parse
import urllib.request
from datetime import date

URL = "https://api.open-meteo.com/v1/forecast"
DUREE_CACHE = 3 * 3600
_cache = {}
_verrou = threading.Lock()

# Codes météo WMO -> (icône, libellé)
TEMPS = {
    0: ("☀️", "Ensoleillé"), 1: ("🌤️", "Peu nuageux"), 2: ("⛅", "Nuageux"), 3: ("☁️", "Couvert"),
    45: ("🌫️", "Brume"), 48: ("🌫️", "Brume"), 51: ("🌦️", "Bruine"), 53: ("🌦️", "Bruine"), 55: ("🌦️", "Bruine"),
    61: ("🌧️", "Pluie faible"), 63: ("🌧️", "Pluie"), 65: ("🌧️", "Forte pluie"),
    80: ("🌦️", "Averses"), 81: ("🌧️", "Averses"), 82: ("⛈️", "Fortes averses"),
    95: ("⛈️", "Orage"), 96: ("⛈️", "Orage"), 99: ("⛈️", "Orage"),
}
JOURS = ("lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim.")


def _telecharger(latitude, longitude):
    parametres = urllib.parse.urlencode({
        "latitude": latitude, "longitude": longitude, "timezone": "Africa/Dakar", "forecast_days": 7,
        "daily": "weathercode,temperature_2m_max,temperature_2m_min,precipitation_sum,"
                 "precipitation_probability_max,windspeed_10m_max",
    })
    with urllib.request.urlopen(f"{URL}?{parametres}", timeout=6) as reponse:
        return json.loads(reponse.read().decode("utf-8"))["daily"]


def previsions(latitude, longitude):
    """Liste de 7 jours {jour, date, icone, libelle, tmax, tmin, pluie_mm, pluie_proba, vent}, ou None."""
    cle = (round(latitude, 2), round(longitude, 2))
    with _verrou:
        en_cache = _cache.get(cle)
        if en_cache and time.time() - en_cache[0] < DUREE_CACHE:
            return en_cache[1]
    try:
        brut = _telecharger(*cle)
        jours = []
        for i, jour in enumerate(brut["time"]):
            icone, libelle = TEMPS.get(brut["weathercode"][i], ("🌡️", ""))
            jours.append({
                "date": jour, "jour": JOURS[date.fromisoformat(jour).weekday()], "icone": icone, "libelle": libelle,
                "tmax": round(brut["temperature_2m_max"][i]), "tmin": round(brut["temperature_2m_min"][i]),
                "pluie_mm": round(brut["precipitation_sum"][i] or 0, 1),
                "pluie_proba": brut["precipitation_probability_max"][i] or 0,
                "vent": round(brut["windspeed_10m_max"][i] or 0),
            })
    except Exception as erreur:
        print(f"[meteo] Prévisions indisponibles : {erreur}")
        return None
    with _verrou:
        _cache[cle] = (time.time(), jours)
    return jours


def conseils(jours):
    """Quelques conseils pratiques tirés des prévisions (récolte, séchage, arrosage, chaleur)."""
    if not jours:
        return []
    resultat = []
    pluvieux = [j for j in jours if j["pluie_mm"] >= 5 or j["pluie_proba"] >= 70]
    if pluvieux:
        premier = pluvieux[0]
        resultat.append(f"🌧️ Pluie attendue {premier['jour']} {premier['date'][8:10]} ({premier['pluie_mm']} mm) : "
                        "rentre ou couvre les récoltes qui sèchent, évite d'épandre l'engrais la veille.")
    else:
        resultat.append("☀️ Pas de pluie prévue cette semaine : pense à arroser, bon moment pour sécher les récoltes.")
    if max(j["tmax"] for j in jours) >= 38:
        resultat.append("🔥 Fortes chaleurs : arrose tôt le matin ou le soir, stocke les récoltes à l'ombre.")
    if max(j["vent"] for j in jours) >= 40:
        resultat.append("💨 Vent fort prévu : protège les jeunes plants et les abris.")
    return resultat
