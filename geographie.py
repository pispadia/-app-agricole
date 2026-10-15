"""Adresses : pays, puis pour le Sénégal région -> département -> commune, puis le village ou quartier.

À chaque étape, l'utilisateur choisit dans la liste ou écrit lui-même (« Autre ») si son lieu
n'y figure pas. Les listes de communes reprennent les principales communes de chaque département ;
elles peuvent être complétées ici sans rien changer d'autre.
"""
import re

# Code ISO, nom affiché, indicatif téléphonique
PAYS = (
    ("SN", "Sénégal", "221"),
    ("GM", "Gambie", "220"),
    ("ML", "Mali", "223"),
    ("MR", "Mauritanie", "222"),
    ("GN", "Guinée", "224"),
    ("GW", "Guinée-Bissau", "245"),
    ("CV", "Cap-Vert", "238"),
    ("CI", "Côte d'Ivoire", "225"),
    ("BF", "Burkina Faso", "226"),
    ("NE", "Niger", "227"),
    ("BJ", "Bénin", "229"),
    ("TG", "Togo", "228"),
    ("GH", "Ghana", "233"),
    ("NG", "Nigeria", "234"),
    ("CM", "Cameroun", "237"),
    ("MA", "Maroc", "212"),
    ("FR", "France", "33"),
)
NOMS_PAYS = {code: nom for code, nom, _ in PAYS}
INDICATIFS = {code: indicatif for code, _, indicatif in PAYS}
PAYS_PAR_DEFAUT = "SN"

# Région -> département -> principales communes
SENEGAL = {
    "Dakar": {
        "Dakar": ["Dakar-Plateau", "Médina", "Gueule Tapée-Fass-Colobane", "Fann-Point E-Amitié", "Grand Dakar",
                  "Biscuiterie", "HLM", "Hann Bel-Air", "Sicap-Liberté", "Dieuppeul-Derklé", "Mermoz-Sacré-Cœur",
                  "Ouakam", "Ngor", "Yoff", "Grand Yoff", "Patte d'Oie", "Parcelles Assainies", "Cambérène",
                  "Gorée"],
        "Guédiawaye": ["Golf Sud", "Sam Notaire", "Ndiarème Limamoulaye", "Wakhinane Nimzatt", "Médina Gounass"],
        "Keur Massar": ["Keur Massar Nord", "Keur Massar Sud", "Malika", "Yeumbeul Nord", "Yeumbeul Sud",
                        "Jaxaay-Parcelles"],
        "Pikine": ["Pikine Est", "Pikine Ouest", "Pikine Nord", "Dalifort", "Djiddah Thiaroye Kao",
                   "Guinaw Rails Nord", "Guinaw Rails Sud", "Thiaroye-sur-Mer", "Thiaroye Gare",
                   "Diamaguène Sicap Mbao", "Mbao"],
        "Rufisque": ["Rufisque Est", "Rufisque Ouest", "Rufisque Nord", "Bargny", "Sébikotane", "Diamniadio",
                     "Sendou", "Sangalkam", "Bambilor", "Yène", "Tivaouane Peulh-Niaga"],
    },
    "Diourbel": {
        "Bambey": ["Bambey", "Baba Garage", "Lambaye", "Ngoye", "Ndondol", "Gawane", "Réfane"],
        "Diourbel": ["Diourbel", "Ndoulo", "Ndindy", "Touré Mbonde", "Tocky Gare", "Dankh Sène"],
        "Mbacké": ["Mbacké", "Touba Mosquée", "Kaël", "Ndame", "Taïba Thiékène", "Dalla Ngabou", "Missirah",
                   "Taïf", "Sadio"],
    },
    "Fatick": {
        "Fatick": ["Fatick", "Diakhao", "Niakhar", "Fimla", "Diofior", "Tataguine", "Ndiob", "Diouroup",
                   "Diarrère", "Djilasse"],
        "Foundiougne": ["Foundiougne", "Sokone", "Karang Poste", "Passy", "Soum", "Toubacouta", "Djilor",
                        "Niodior", "Dionewar", "Bassoul"],
        "Gossas": ["Gossas", "Colobane", "Ouadiour", "Mbar", "Patar Lia"],
    },
    "Kaffrine": {
        "Birkelane": ["Birkelane", "Mabo", "Keur Mboucki", "Ndiognick"],
        "Kaffrine": ["Kaffrine", "Nganda", "Gniby", "Kathiotte", "Boulel", "Kahi"],
        "Koungheul": ["Koungheul", "Ida Mouride", "Lour Escale", "Missirah Wadène", "Maka Yop", "Saly Escale"],
        "Malem-Hodar": ["Malem-Hodar", "Sagna", "Darou Minam 2", "Ndioum Ngainth", "Dianké Souf"],
    },
    "Kaolack": {
        "Guinguinéo": ["Guinguinéo", "Fass", "Mboss", "Ngathie Naoudé", "Mbadakhoune", "Ndiago", "Gagnick"],
        "Kaolack": ["Kaolack", "Kahone", "Ndoffane", "Gandiaye", "Sibassor", "Latmingué", "Keur Baka",
                    "Ndiédieng", "Thiomby", "Ndiaffate"],
        "Nioro du Rip": ["Nioro du Rip", "Keur Madiabel", "Médina Sabakh", "Paoskoto", "Wack Ngouna",
                         "Porokhane", "Kayemor", "Taïba Niassène"],
    },
    "Kédougou": {
        "Kédougou": ["Kédougou", "Bandafassi", "Fongolimbi", "Dindéfélo", "Ninéfécha", "Tomboronkoto", "Dimboli"],
        "Salémata": ["Salémata", "Dakatéli", "Dar Salam", "Ethiolo", "Kévoye", "Oubadji"],
        "Saraya": ["Saraya", "Bembou", "Khossanto", "Missirah Sirimana", "Sabodala", "Médina Baffé"],
    },
    "Kolda": {
        "Kolda": ["Kolda", "Dabo", "Salikégné", "Saré Yoba Diéga", "Mampatim", "Dioulacolon", "Médina El Hadji",
                  "Thiétty", "Bagadadji"],
        "Médina Yoro Foulah": ["Médina Yoro Foulah", "Pata", "Fafacourou", "Badion", "Ndorna", "Niaming"],
        "Vélingara": ["Vélingara", "Diaobé-Kabendou", "Kounkané", "Bonconto", "Linkéring", "Pakour",
                      "Saré Coly Sallé", "Kandia"],
    },
    "Louga": {
        "Kébémer": ["Kébémer", "Guéoul", "Ndande", "Sagatta Gueth", "Darou Mousty", "Mbacké Cadior", "Thieppe",
                    "Kanène Ndiob"],
        "Linguère": ["Linguère", "Dahra", "Barkédji", "Yang-Yang", "Dodji", "Mboula", "Sagatta Djoloff",
                     "Thiamène Djolof"],
        "Louga": ["Louga", "Coki", "Keur Momar Sarr", "Nguidila", "Sakal", "Léona", "Ndiagne", "Niomré",
                  "Mbédiène", "Nguer Malal"],
    },
    "Matam": {
        "Kanel": ["Kanel", "Ouro Sidy", "Waoundé", "Sinthiou Bamambé", "Hamady Ounaré", "Orkadiéré", "Semmé",
                  "Dembancané", "Aouré"],
        "Matam": ["Matam", "Ourossogui", "Thilogne", "Nabadji Civol", "Ogo", "Agnam Civol", "Bokidiawé", "Dabia"],
        "Ranérou-Ferlo": ["Ranérou", "Vélingara Ferlo", "Lougré Thiolly", "Oudalaye"],
    },
    "Saint-Louis": {
        "Dagana": ["Dagana", "Richard-Toll", "Rosso Sénégal", "Ross Béthio", "Ndombo Alarar", "Gaé", "Mbane",
                   "Ronkh", "Bokhol", "Gnith"],
        "Podor": ["Podor", "Ndioum", "Golléré", "Guédé Chantier", "Aéré Lao", "Pété", "Galoya Toucouleur",
                  "Demette", "Mboumba", "Gamadji Saré", "Bodé Lao", "Méry", "Cas-Cas"],
        "Saint-Louis": ["Saint-Louis", "Mpal", "Fass Ngom", "Gandon", "Ndiébène Gandiole"],
    },
    "Sédhiou": {
        "Bounkiling": ["Bounkiling", "Madina Wandifa", "Ndiamacouta", "Diaroumé", "Bogal", "Inor", "Djinany"],
        "Goudomp": ["Goudomp", "Samine", "Tanaff", "Diattacounda", "Djibanar", "Kaour", "Simbandi Brassou",
                    "Karantaba"],
        "Sédhiou": ["Sédhiou", "Marsassoum", "Diendé", "Bambali", "Djiredji", "Oudoucar", "Sakar",
                    "Diannah Malary"],
    },
    "Tambacounda": {
        "Bakel": ["Bakel", "Diawara", "Kidira", "Gabou", "Moudéry", "Bélé", "Sinthiou Fissa", "Ballou"],
        "Goudiry": ["Goudiry", "Kothiary", "Bala", "Koussan", "Dianké Makha", "Boynguel Bamba",
                    "Sinthiou Mamadou Boubou"],
        "Koumpentoum": ["Koumpentoum", "Malème Niani", "Kouthiaba Wolof", "Bamba Thialène", "Payar", "Méréto"],
        "Tambacounda": ["Tambacounda", "Koussanar", "Missirah", "Dialacoto", "Makacolibantang", "Ndoga Babacar",
                        "Niani Toucouleur", "Sinthiou Malème"],
    },
    "Thiès": {
        "Mbour": ["Mbour", "Joal-Fadiouth", "Saly Portudal", "Ngaparou", "Somone", "Popenguine-Ndayane",
                  "Nguékhokh", "Thiadiaye", "Sindia", "Malicounda", "Nguéniène", "Fissel", "Sandiara", "Séssène",
                  "Diass", "Ndiaganiao"],
        "Thiès": ["Thiès Est", "Thiès Ouest", "Thiès Nord", "Pout", "Khombole", "Fandène", "Keur Moussa",
                  "Notto Diobass", "Tassette", "Ndiéyène Sirakh", "Cayar", "Diender", "Thiénaba", "Touba Toul"],
        "Tivaouane": ["Tivaouane", "Mboro", "Méckhé", "Pire Goureye", "Pambal", "Taïba Ndiaye", "Mérina Dakhar",
                      "Niakhène", "Notto Gouye Diama", "Darou Khoudoss", "Mont-Rolland", "Pékesse"],
    },
    "Ziguinchor": {
        "Bignona": ["Bignona", "Thionck-Essyl", "Diouloulou", "Kafountine", "Sindian", "Tenghory", "Kataba 1",
                    "Niamone", "Ouonck", "Djinaki", "Coubalan", "Suelle"],
        "Oussouye": ["Oussouye", "Mlomp", "Oukout", "Djembéring", "Santhiaba Manjacque"],
        "Ziguinchor": ["Ziguinchor", "Niaguis", "Nyassia", "Adéane", "Boutoupa-Camaracounda", "Enampore"],
    },
}

AUTRE = "__autre__"
LONGUEUR_MAX = 80


def _champ(formulaire, nom):
    """Valeur choisie dans la liste, ou saisie dans « Autre »."""
    valeur = (formulaire.get(nom) or "").strip()
    if valeur == AUTRE:
        valeur = (formulaire.get(nom + "_autre") or "").strip()
    return " ".join(valeur.split())[:LONGUEUR_MAX]


def lieu_valide(formulaire):
    """{pays, region, departement, commune, localite} lu dans le formulaire, ou ValueError."""
    pays = (formulaire.get("pays") or "").strip()
    if pays not in NOMS_PAYS:
        raise ValueError("Choisis ton pays.")
    lieu = {"pays": pays}
    for niveau, message in (("region", "Indique ta région."), ("departement", "Indique ton département."),
                            ("commune", "Indique ta commune ou ta ville.")):
        lieu[niveau] = _champ(formulaire, niveau)
        # Hors Sénégal, le département est facultatif (tous les pays n'en ont pas)
        if not lieu[niveau] and not (niveau == "departement" and pays != "SN"):
            raise ValueError(message)
    lieu["localite"] = _champ(formulaire, "localite") or None
    lieu["departement"] = lieu["departement"] or None
    return lieu


def texte_lieu(utilisateur, avec_pays=False):
    """« Keur Massar (Malika), Dakar » à partir des colonnes de l'utilisateur ; '' si inconnu."""
    try:
        commune, localite, region, pays = (utilisateur["commune"], utilisateur["localite"],
                                           utilisateur["region"], utilisateur["pays"])
    except (KeyError, IndexError):
        return ""
    if not commune:
        return ""
    texte = f"{localite}, {commune}" if localite else commune
    if region and region != commune:
        texte += f", {region}"
    if avec_pays and pays and pays != PAYS_PAR_DEFAUT:
        texte += f", {NOMS_PAYS.get(pays, pays)}"
    return texte


def telephone_international(texte, pays=PAYS_PAR_DEFAUT):
    """'77 123 45 67' (Sénégal) -> '+221771234567' ; '+33 6 12…' gardé tel quel. ValueError si invalide."""
    texte = (texte or "").strip()
    chiffres = re.sub(r"\D", "", texte)
    if texte.startswith("+"):
        complet = chiffres
    elif chiffres.startswith("00"):
        complet = chiffres[2:]
    else:
        indicatif = INDICATIFS.get(pays, INDICATIFS[PAYS_PAR_DEFAUT])
        local = chiffres.lstrip("0") if pays == "FR" else chiffres
        complet = chiffres if chiffres.startswith(indicatif) and len(chiffres) > 10 else indicatif + local
    if not 10 <= len(complet) <= 15:
        raise ValueError("Numéro de téléphone invalide (ex : 77 123 45 67).")
    return "+" + complet
