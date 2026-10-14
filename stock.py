"""Stock des annonces : les quantités sont du texte libre (« 500 kg », « 1,5 tonne »,
« 150 pièces »). On les lit en (valeur, unité) pour décompter les commandes livrées et
refuser une commande plus grande que le stock. Quand les unités ne se comparent pas
(« 3 sacs » commandés sur « 200 kg »), on ne touche à rien."""
import re

from prix_marche import sans_accents

# Unités de masse ramenées au kilo
MASSES = {"kg": 1, "kgs": 1, "kilo": 1, "kilos": 1, "kilogramme": 1, "kilogrammes": 1,
          "t": 1000, "tonne": 1000, "tonnes": 1000, "g": 0.001, "gramme": 0.001, "grammes": 0.001}


def lire_quantite(texte):
    """« 1,5 tonne » -> (1500.0, 'kg') ; « 150 pièces » -> (150.0, 'piece') ; None si illisible."""
    correspondance = re.match(r"\s*(\d+(?:[.,]\d+)?)\s*(.*)$", texte or "")
    if not correspondance:
        return None
    valeur = float(correspondance.group(1).replace(",", "."))
    unite = sans_accents(correspondance.group(2)).lower().strip(" .")
    unite = unite.split()[0] if unite else ""
    if unite in MASSES:
        return valeur * MASSES[unite], "kg"
    # « sacs » et « sac », « pièces » et « pièce » : même unité
    return valeur, unite[:-1] if unite.endswith(("s", "x")) and len(unite) > 2 else unite


def ecrire_quantite(valeur_kg_ou_unites, texte_annonce):
    """Écrit la quantité restante dans l'unité d'origine de l'annonce (« 0,95 tonne », « 450 kg »)."""
    correspondance = re.match(r"\s*\d+(?:[.,]\d+)?\s*(.*)$", texte_annonce or "")
    libelle = correspondance.group(1).strip() if correspondance else ""
    premier_mot = sans_accents(libelle).lower().strip(" .").split()[0] if libelle else ""
    valeur = valeur_kg_ou_unites / MASSES.get(premier_mot, 1)
    nombre = f"{valeur:.2f}".rstrip("0").rstrip(".").replace(".", ",")
    return f"{nombre} {libelle}".strip()


def reste_apres(quantite_annonce, quantite_commandee):
    """Quantité restante (texte) après la commande, ou None si les unités ne se comparent pas."""
    stock, commande = lire_quantite(quantite_annonce), lire_quantite(quantite_commandee)
    if not stock or not commande or stock[1] != commande[1]:
        return None
    return max(stock[0] - commande[0], 0), ecrire_quantite(max(stock[0] - commande[0], 0), quantite_annonce)


def depasse_le_stock(quantite_annonce, quantite_commandee):
    """Vrai si la commande demande plus que le stock (unités comparables seulement)."""
    stock, commande = lire_quantite(quantite_annonce), lire_quantite(quantite_commandee)
    return bool(stock and commande and stock[1] == commande[1] and commande[0] > stock[0] + 1e-9)


def decompter_livraison(connexion_bd, commande_id):
    """Après une livraison : retire la quantité livrée du stock de l'annonce ; l'annonce passe
    « épuisée » quand il ne reste rien. Retourne un message pour l'agriculteur, ou None."""
    ligne = connexion_bd.execute(
        """SELECT recoltes.id, recoltes.quantite, commandes.quantite_demandee FROM commandes
           JOIN recoltes ON commandes.recolte_id = recoltes.id WHERE commandes.id = ?""", (commande_id,)
    ).fetchone()
    if ligne is None:
        return None
    resultat = reste_apres(ligne["quantite"], ligne["quantite_demandee"])
    if resultat is None:
        return "Pense à mettre à jour la quantité de ton annonce."
    restant, texte = resultat
    if restant <= 0:
        connexion_bd.execute("UPDATE recoltes SET quantite = ?, statut = 'epuise' WHERE id = ?", (texte, ligne["id"]))
        return "Stock épuisé : ton annonce est passée « épuisée »."
    connexion_bd.execute("UPDATE recoltes SET quantite = ? WHERE id = ?", (texte, ligne["id"]))
    return f"Stock mis à jour : il reste {texte}."
