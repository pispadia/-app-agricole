"""Traduction de l'interface en wolof.

Usage dans les templates : {{ "Texte en français" | t }}. Si la langue choisie est le
wolof et que le texte est traduit ci-dessous, la traduction s'affiche ; sinon le texte
français reste affiché. Ajouter une traduction = ajouter une ligne au dictionnaire.
Traductions à faire relire par un locuteur natif.
"""
from flask import redirect, request, session, url_for
from jinja2 import pass_context

from core import app

LANGUES = {"fr": "Français", "wo": "Wolof"}

WOLOF = {
    # Menu
    "Accueil": "Njëlbéen",
    "Tableau de bord": "Sama xët",
    "Notifications": "Yégle yi",
    "Mon profil": "Sama profil",
    "Déconnexion": "Génn",
    "Connexion": "Dugg",
    "Inscription": "Bindu",
    "Installer l'app": "Samp app bi",
    "Passer Premium": "Jël Premium",
    # Accueil
    "Bienvenue sur l'App Agricole": "Dalal ak jàmm ci App Agricole",
    "La plateforme qui connecte agriculteurs, clients et fournisseurs.":
        "Bérëb bi di boole beykat yi, jëndkat yi ak jaaykat yi.",
    "Créer un compte": "Ubbi kont",
    "Se connecter": "Dugg",
    # Connexion / inscription
    "Email": "Email",
    "Mot de passe": "Baatu jàll",
    "Mot de passe oublié ?": "Fàtte nga sa baatu jàll ?",
    "Nom complet": "Sa tur ak sa sant",
    "Mot de passe (8 caractères minimum)": "Baatu jàll (8 araf lu néew)",
    "Téléphone pour les alertes SMS (optionnel, jamais affiché)":
        "Telefon ngir jot SMS (bu la neexee, kenn du ko gis)",
    "Je suis...": "Maa ngi...",
    "Client": "Jëndkat",
    "Agriculteur": "Beykat",
    "Fournisseur (semences / pépinières)": "Jaaykatu jiwu",
    "Organisme de financement": "Kurél buy bóole xaalis",
    "S'inscrire": "Bindu",
    # Espace agriculteur
    "Espace Agriculteur": "Bérëbu beykat bi",
    "Voir les prix du marché": "Xool njëgu marse bi",
    "Bienvenue": "Dalal ak jàmm",
    "+ Publier une récolte": "+ Siiwal ngóob",
    "Voir mes commandes reçues": "Xool ndigal yi ma jot",
    "Acheter semences / pépinières": "Jënd jiwu",
    "Financement": "Xaalis",
    "Mes statistiques": "Samay limu jaay",
    "Inviter et gagner du Premium": "Woo ay nit te am Premium",
    "Mes récoltes publiées": "Samay ngóob yi ma siiwal",
    "Disponible": "Am na",
    "Épuisé": "Jeex na",
    "Détail": "Benn-benn",
    "Gros": "Ci kilo yu bare",
    "Disponible le": "Am na ci",
    "Modifier": "Soppi",
    "Partager sur WhatsApp": "Yónnee ci WhatsApp",
    "Voir l'annonce": "Xool yéenekaay bi",
    "Marquer épuisé": "Jeex na",
    "Marquer disponible": "Am na",
    "Tu n'as encore publié aucune récolte.": "Siiwaloo benn ngóob ba leegi.",
    # Publier une récolte
    "Publier une récolte": "Siiwal ngóob",
    "Nom du produit (ex: Tomates)": "Turu meññeef mi (ex: Tamaate)",
    "Quantité (ex: 200 kg)": "Lim bi (ex: 200 kg)",
    "Prix au détail (ex: 500 FCFA / kg)": "Njëg benn-benn (ex: 500 FCFA / kg)",
    "Voir les prix du marché pour fixer ton prix": "Xool njëgu marse bi ngir tëral sa njëg",
    "Prix en gros (optionnel)": "Njëg ci kilo yu bare (bu la neexee)",
    "Prix en gros (ex: 400 FCFA / kg)": "Njëg ci kilo yu bare (ex: 400 FCFA / kg)",
    "Quantité minimum pour le prix en gros (ex: à partir de 50 kg)":
        "Lim bu gën a tuuti ngir njëg googu (ex: 50 kg ba ci kaw)",
    "Date de disponibilité": "Bés bi mu nekk",
    "Localité de production (ex: Thiès)": "Dëkk bi mu bayu (ex: Thiès)",
    "Description (optionnel)": "Leeral (bu la neexee)",
    "Photo du produit (optionnel)": "Nataalu meññeef mi (bu la neexee)",
    "Publier": "Siiwal",
    "← Retour à mon espace": "← Dellu ci sama bérëb",
    # Commandes
    "Commandes reçues": "Ndigal yi ma jot",
    "En attente": "Mu ngi xaar",
    "Confirmée": "Dëggal nañu ko",
    "Livrée": "Jox nañu ko",
    "Annulée": "Neenal nañu ko",
    "Confirmer": "Dëggal",
    "Marquer livrée": "Jox naa ko",
    "Refuser / annuler": "Bañ / neenal",
    "Discuter": "Waxtaan",
    "Aucune commande reçue pour le moment.": "Jotoo benn ndigal ba leegi.",
    # Messagerie
    "Discussion avec": "Waxtaan ak",
    "Ton message...": "Sa bataaxal...",
    "Envoyer": "Yónnee",
    "← Retour aux commandes": "← Dellu ci ndigal yi",
}


@pass_context
def traduire(contexte, texte):
    # pass_context empêche Jinja de pré-calculer le filtre à la compilation du template
    # (sinon la langue du premier affichage resterait figée pour tout le monde)
    if session.get("langue") == "wo":
        return WOLOF.get(texte, texte)
    return texte


app.add_template_filter(traduire, "t")


@app.context_processor
def injecter_langue():
    return {"langue": session.get("langue", "fr"), "langues": LANGUES}


@app.route("/langue/<code>")
def changer_langue(code):
    if code in LANGUES:
        session["langue"] = code
    # Retour sur la page d'où l'on vient (seulement sur ce site)
    if request.referrer and request.referrer.startswith(request.host_url):
        return redirect(request.referrer)
    return redirect(url_for("accueil"))
