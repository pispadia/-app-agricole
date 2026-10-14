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
    "Récoltes": "Ngóob yi",
    "Je vends mes récoltes": "Damay jaay samay ngóob",
    "J'achète": "Damay jënd",
    "Déjà inscrit ?": "Bindu nga ba noppi ?",
    "agriculteurs": "beykat",
    "annonces": "yéenekaay",
    "commandes livrées": "ndigal yu ñu jox",
    "Dernières récoltes": "Ngóob yu mujj yi",
    "Voir toutes les récoltes": "Xool ngóob yépp",
    "Comment ça marche": "Naka la doxe",
    "L'agriculteur publie sa récolte (gratuit).": "Beykat bi dafay siiwal ngóobam (amul fay).",
    "Le client commande ou réserve, en retrait ou en livraison.": "Jëndkat bi dafay ndigal walla denc, mu jël ko walla ñu indil ko ko.",
    "Paiement à la livraison ou avec Wave.": "Fay bu ñu ko indilee walla ak Wave.",
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
    "Masquée par la modération": "Nëbbu nañu ko",
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
    "Pas encore récoltée ? Mets la date prévue : les clients pourront la réserver.":
        "Góobagoo ko ba leegi ? Bind bés bi nga ko xaar : jëndkat yi mën nañu ko denc.",
    "Localité de production (ex: Thiès)": "Dëkk bi mu bayu (ex: Thiès)",
    "Description (optionnel)": "Leeral (bu la neexee)",
    "Photo du produit (optionnel)": "Nataalu meññeef mi (bu la neexee)",
    "Faire vérifier mon compte": "Seetlu sama kont",
    "Autres photos (optionnel, 3 maximum)": "Yeneen nataal (bu la neexee, 3 ci lu ëpp)",
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
    # Menu, pied de page et accueil
    "Commandes": "Ndigal yi",
    "Carte": "Kaart",
    "Prix du marché": "Njëgu marse bi",
    "Premium": "Premium",
    "Conditions d'utilisation": "Sarti jëfandikoo",
    "Confidentialité": "Sutura",
    "Contact": "Jokkoo ak nun",
    "Achetez directement aux producteurs du Sénégal, au juste prix.":
        "Jëndal ci beykati Senegaal yi ci seen loxo, ci njëg ju jub.",
    "Publication": "Siiwal",
    "Commande": "Ndigal",
    "Paiement": "Fay",
    "Notifications sur ton téléphone": "Yégle ci sa telefon",
    "Reçois les nouvelles commandes, messages et changements de statut directement sur ton téléphone, gratuitement.":
        "Jot ndigal yu bees yi, bataaxal yi ak li soppiku ci sa telefon, te doo fay dara.",
    "Activer les notifications sur cet appareil": "Taal yégle yi ci jumtukaay bii",
    # Espace agriculteur
    "Bonjour": "Salaamaalekum",
    "Voici tes ventes et tes récoltes en ligne.": "Yii ñooy say jaay ak say ngóob yu nekk ci internet.",
    "commande(s) en attente de ta réponse": "ndigal yu xaar sa tontu",
    "Réponds vite : les clients achètent plus aux agriculteurs qui confirment rapidement.":
        "Tontu bu gaaw : jëndkat yi dañuy gën a jënd ci beykat yi gaaw a dëggal.",
    "Répondre": "Tontu",
    "Fais vérifier ton compte": "Seetlulu sa kont",
    "Ta pièce est en cours de vérification.": "Ñu ngi seet sa kayit.",
    "Le badge « Vérifié » rassure les clients et fait vendre plus.":
        "Màndarga « Vérifié » dafay dalal xelu jëndkat yi te yokk say jaay.",
    "Annonces en ligne": "Yéenekaay yu nekk ci internet",
    "Commandes en attente": "Ndigal yu ngi xaar",
    "FCFA de ventes livrées": "FCFA ci jaay yu ñu jox",
    "avis clients": "xalaatu jëndkat",
    "Pas encore d'avis": "Amagul benn xalaat",
    "Ma boutique et mon affiche QR": "Sama bitig ak sama afiis QR",
    "À poser sur ton étal au marché": "Ngir teg ko ci sa taabal ci marse bi",
    "Mon bilan du mois": "Sama mbooleem weer wi",
    "Ventes, avis, conseils prix": "Jaay, xalaat, digle ci njëg",
    "Ventes, produits les plus demandés": "Jaay, meññeef yi ñu gën a laaj",
    "Conseiller agricole": "Digalekatu mbay",
    "Maladies, engrais, semis : demande à l'IA": "Feebar, sunguf, ji : laajal IA bi",
    "Météo agricole": "Jawwu mbay",
    "7 jours et conseils": "7 fan ak ay digle",
    "Fixe le bon prix": "Tëral njëg ju jub",
    "1 mois offert par filleul": "1 weer ñu may la ci ku nekk ku nga woo",
    "Semences et pépinières": "Jiwu ak garab yu ndaw",
    "Acheter auprès des fournisseurs": "Jënd ci jaaykat yi",
    "Crédits et aides agricoles": "Bor ak ndimbal ci mbay",
    "Badge de confiance": "Màndargay kóolute",
    "Promotion": "Wàññi njëg",
    "Mettre en promo": "Wàññi njëg li",
    "jours": "fan",
    "Lancer": "Tàmbali",
    "Arrêter la promo": "Taxawal wàññi gi",
    "Pas de réseau au champ ? Remplis quand même : l'annonce partira toute seule dès que le réseau revient.":
        "Amul rezo ci tool bi ? Bindal rekk : yéenekaay bi dina dem boppam bu rezo bi délloo.",
    "Écrire la description avec l'IA": "Bind leeral bi ak IA bi",
    # Commandes reçues : fiabilité du client
    "note(s) d'agriculteurs": "nòtu beykat",
    "Pas encore noté": "Nòtuñu ko ba leegi",
    "commande(s) livrée(s)": "ndigal yu ñu jox",
    "Ta note pour ce client": "Sa nòt ci jëndkat bii",
    "Note ce client": "Nòtal jëndkat bii",
    "ex : absent au rendez-vous": "ex : ñëwul ci ndaje mi",
    "Noter": "Nòtal",
    # Boutique
    "Producteur": "Beykat",
    "Membre depuis": "Bokk na fi ca",
    "Suivi": "Mu ngi ci sa topp",
    "Suivre": "Topp",
    "Créer un compte pour commander": "Ubbil kont ngir ndigal",
    "Mon affiche QR": "Sama afiis QR",
    "Récoltes en vente": "Ngóob yu ñuy jaay",
    "Aucune récolte en vente pour le moment.": "Amul benn ngóob buñuy jaay ba leegi.",
    "Suis ce producteur pour être prévenu de sa prochaine récolte.":
        "Toppal beykat bii ngir ñu yégal la ngóobam bu topp.",
    "Ce que disent ses clients": "Li jëndkatam yi wax",
    "Tous les avis": "Xalaat yépp",
    # Espace client et favoris
    "Espace Client": "Bérëbu jëndkat bi",
    "Achète directement aux agriculteurs, au juste prix.": "Jëndal ci beykat yi ci seen loxo, ci njëg ju jub.",
    "Mes commandes": "Samay ndigal",
    "Mon panier": "Sama pañe",
    "en cours": "ñu ngi ci",
    "Suivi, reçus et avis": "Topp, reçu ak xalaat",
    "Mes favoris": "Li ma bëgg",
    "Annonces gardées et agriculteurs suivis": "Yéenekaay yi nga denc ak beykat yi ngay topp",
    "Mes alertes produits": "Samay yégle meññeef",
    "Prévenu dès qu'un produit arrive": "Ñu yégal la bu meññeef ñëwee",
    "Compare avant d'acheter": "Méngaleel balaa ngay jënd",
    "Invite un agriculteur": "Wooal benn beykat",
    "Récoltes disponibles": "Ngóob yu am",
    "Aucune récolte ne correspond à ta recherche.": "Amul benn ngóob bu dëppoo ak li ngay seet.",
    "Ta note de fiabilité donnée par les agriculteurs": "Sa nòtu kóolute bi beykat yi la jox",
    "Les annonces que tu as gardées et les agriculteurs que tu suis.":
        "Yéenekaay yi nga denc ak beykat yi ngay topp.",
    "Catalogue": "Katalog",
    "Agriculteurs suivis": "Beykat yi ngay topp",
    "Tu es prévenu dès qu'un agriculteur suivi publie une nouvelle récolte.":
        "Dinañu la yégal bu beykat bu ngay topp siiwalee ngóob bu bees.",
    "annonce(s) en ligne": "yéenekaay ci internet",
    "Ne plus suivre": "Bàyyi topp",
    "Tu ne suis encore aucun agriculteur. Sur une annonce, touche « Suivre cet agriculteur ».":
        "Toppoo benn beykat ba leegi. Ci benn yéenekaay, bësal « Suivre cet agriculteur ».",
    "Annonces gardées": "Yéenekaay yi nga denc",
    "Plus disponible": "Amatul",
    "Commander": "Ndigal",
    "Retirer": "Far",
    "Aucune annonce gardée. Sur une annonce, touche « Ajouter aux favoris ».":
        "Dencoo benn yéenekaay. Ci benn yéenekaay, bësal « Ajouter aux favoris ».",
    # Météo et conseiller
    "Indique ta localité pour voir la météo des 7 prochains jours.":
        "Bindal sa dëkk ngir gis jawwu 7 fan yiy ñëw.",
    "Pose ta question sur tes cultures : maladie d'une plante, engrais, arrosage, semis, conservation des récoltes... Ajoute une photo de la plante si tu veux.":
        "Laajal sa laaj ci say mbay : feebaru garab, sunguf, suuxat, ji, denc ngóob... Yokkal nataalu garab gi bu la neexee.",
    "Demander conseil": "Laaj digle",
    # Bilan du mois
    "Mon bilan de": "Sama mbooleem",
    "Tes ventes, tes clients et des conseils pour le mois suivant.":
        "Say jaay, say jëndkat ak ay digle ngir weer wiy ñëw.",
    "Voir": "Xool",
    "livrées": "yu ñu jox",
    "nouvel(s) avis": "xalaat yu bees",
    "nouveaux abonnés": "ñu bees ñuy la topp",
    "Produits les plus demandés": "Meññeef yi ñu gën a laaj",
    "commande(s)": "ndigal",
    "Aucune commande ce mois-là.": "Amul benn ndigal ci weer woowu.",
    "annonce(s) publiée(s) ce mois-là.": "yéenekaay yu ñu siiwal ci weer woowu.",
    "Conseils prix (annonces en ligne)": "Digle ci njëg (yéenekaay yu nekk ci internet)",
    "Tes prix sont proches du prix courant du marché (ou il n'y a pas encore assez d'annonces pour comparer).":
        "Sa njëg yi jege nañu njëgu marse bi (walla amagul yéenekaay yu doy ngir méngale).",
    "Recevoir ce bilan par e-mail au début de chaque mois": "Jot mbooleem mii ci e-mail ci njëlbéenu weer wu nekk",
    "Enregistrer": "Denc",
    # Vérification du compte
    "Badge « Agriculteur vérifié »": "Màndarga « Agriculteur vérifié »",
    "Ton compte est vérifié : le badge apparaît sur toutes tes annonces.":
        "Seetlu nañu sa kont : màndarga mi dafay feeñ ci say yéenekaay yépp.",
    "Ta pièce est en cours de vérification. Tu seras prévenu par SMS.":
        "Ñu ngi seet sa kayit. Dinañu la yégal ci SMS.",
    "Ta dernière pièce n'a pas pu être vérifiée. Envoie une photo plus lisible.":
        "Mënuñoo seet sa kayit bu mujj bi. Yónneel nataal bu gën a leer.",
    "Les clients font plus confiance aux agriculteurs vérifiés. Envoie une photo de ta carte d'identité (ou passeport) : le nom doit correspondre à celui de ton compte.":
        "Jëndkat yi dañuy gën a wóolu beykat yi ñu seetlu. Yónneel nataalu sa kàrt didantite (walla paaspoor) : tur wi war na dëppoo ak bi nekk ci sa kont.",
    "La photo est vue uniquement par l'équipe App Agricole et supprimée dès la vérification.":
        "Ekibu App Agricole rekk ay gis nataal bi, te dinañu ko far bu seet gi jeexee.",
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
