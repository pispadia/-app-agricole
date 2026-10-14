"""Assistant IA (Claude, d'Anthropic) : rédaction d'annonces et conseils agricoles.

Activé seulement si la variable ANTHROPIC_API_KEY est définie (clé payante, console.anthropic.com).
Modèle par défaut : claude-opus-5-5 ; IA_MODELE permet d'en choisir un autre (ex : claude-haiku-5-5,
beaucoup moins cher et plus rapide). Les réponses courtes (effort « low ») gardent la page rapide ;
le délai est borné pour ne jamais bloquer le serveur.
"""
import os

import anthropic

MODELE_PAR_DEFAUT = "claude-opus-5-5"
DELAI_SECONDES = 25  # le serveur web coupe les requêtes trop longues : on abandonne avant

SYSTEME = (
    "Tu es l'assistant d'App Agricole, une plateforme qui met en relation agriculteurs, clients et "
    "fournisseurs au Sénégal. Tu réponds en français simple et clair, avec des phrases courtes, à des "
    "agriculteurs qui ne sont pas toujours à l'aise avec l'écrit. Tu tiens compte du contexte sénégalais "
    "(saison des pluies d'hivernage de juin à octobre, saison sèche, cultures courantes : mil, arachide, "
    "oignon, maïs, niébé, riz, mangue, tomate ; marchés locaux ; produits et intrants disponibles au Sénégal)."
)


class IAIndisponible(Exception):
    """L'assistant n'a pas pu répondre (pas de clé, délai dépassé, refus, panne) : message pour l'utilisateur."""


def ia_active():
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _client():
    return anthropic.Anthropic(timeout=DELAI_SECONDES, max_retries=1)


def _demander(contenu, max_tokens):
    if not ia_active():
        raise IAIndisponible("L'assistant IA n'est pas encore activé sur App Agricole.")
    try:
        reponse = _client().beta.messages.create(
            model=os.environ.get("IA_MODELE", MODELE_PAR_DEFAUT),
            max_tokens=max_tokens,
            system=SYSTEME,
            messages=[{"role": "user", "content": contenu}],
            output_config={"effort": "low"},
            # Si le modèle décline la demande, l'API la relance sur le modèle de secours recommandé
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.APITimeoutError:
        raise IAIndisponible("L'assistant met trop de temps à répondre. Réessaie avec une demande plus courte.")
    except anthropic.RateLimitError:
        raise IAIndisponible("L'assistant est très sollicité. Réessaie dans une minute.")
    except anthropic.APIStatusError as erreur:
        print(f"[ia] Erreur API {erreur.status_code} : {erreur.message}")
        raise IAIndisponible("L'assistant est momentanément indisponible. Réessaie plus tard.")
    except anthropic.APIConnectionError:
        raise IAIndisponible("Impossible de joindre l'assistant. Réessaie plus tard.")

    if reponse.stop_reason == "refusal":
        raise IAIndisponible("L'assistant ne peut pas répondre à cette demande.")
    texte = "\n".join(bloc.text for bloc in reponse.content if bloc.type == "text").strip()
    if not texte:
        raise IAIndisponible("L'assistant n'a pas su répondre. Reformule ta demande.")
    return texte


def rediger_annonce(produit, quantite="", localite="", notes="", prix_marche=None):
    """Description d'annonce (3 à 5 phrases) à partir de quelques mots de l'agriculteur."""
    details = [f"Produit : {produit}"]
    if quantite:
        details.append(f"Quantité : {quantite}")
    if localite:
        details.append(f"Localité : {localite}")
    if notes:
        details.append(f"Ce que l'agriculteur en dit : {notes}")
    if prix_marche:
        details.append(f"Prix médian constaté sur la plateforme : {prix_marche} FCFA/kg")
    return _demander(
        "Écris la description d'une annonce de vente pour cette récolte, en 3 à 5 phrases courtes, "
        "attrayante mais honnête : n'invente aucune qualité, certification ou chiffre qui n'est pas dans "
        "les informations. Pas de numéro de téléphone, pas d'adresse, pas de titre, pas de liste à puces : "
        "seulement le texte de la description.\n\n" + "\n".join(details),
        max_tokens=600,
    )


def conseil_agricole(question, photo=None):
    """Réponse à une question agricole ; `photo` : (type_mime, données base64) d'une plante, facultative."""
    contenu = []
    if photo:
        type_mime, donnees = photo
        contenu.append({"type": "image", "source": {"type": "base64", "media_type": type_mime, "data": donnees}})
    contenu.append({"type": "text", "text": (
        "Question d'un agriculteur :\n" + question + "\n\n"
        "Réponds de façon pratique et concrète en 150 mots maximum. Si la question porte sur une maladie "
        "ou un ravageur, donne les causes probables et des solutions accessibles au Sénégal, en commençant "
        "par les moins chères. Pour les produits phytosanitaires, rappelle de respecter les doses et de "
        "demander conseil à un technicien agricole (ANCAR, ISRA) en cas de doute. Si tu n'es pas sûr, dis-le."
    )})
    return _demander(contenu, max_tokens=1200)
