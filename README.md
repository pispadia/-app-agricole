# App Agricole

Plateforme locale qui relie agriculteurs, clients, fournisseurs de semences et financeurs.

## Lancer en local

```powershell
python -m pip install -r requirements.txt
python app.py
```

Ouvre ensuite `http://127.0.0.1:5000`.

## Configuration de production

Copie `.env.example` dans les variables d'environnement de l'hébergeur, puis définis une valeur `SECRET_KEY` longue et aléatoire (par exemple avec `python -c "import secrets; print(secrets.token_hex(32))"`). Sans elle, l'application refuse de démarrer en production. Ne lance jamais l'application avec le débogage Flask activé en production. Une URL PostgreSQL peut être fournie avec `DATABASE_URL`; SQLite reste utilisé localement.

Pour le « mot de passe oublié », crée un compte gratuit sur [Brevo](https://www.brevo.com), valide une adresse d'expédition, puis définis `BREVO_API_KEY` et `EMAIL_EXPEDITEUR`. En local sans ces variables, le lien de réinitialisation s'affiche dans la console.

**Installation sur téléphone** : l'application est installable (application web progressive). Sur Android, le bouton « 📲 Installer l'app » apparaît dans le menu, ou menu Chrome > « Ajouter à l'écran d'accueil » ; sur iPhone, Safari > Partager > « Sur l'écran d'accueil ». Sans réseau, une page « Pas de connexion internet » s'affiche. Le site doit être servi en HTTPS (c'est le cas sur Render).

**Livraison** : à la commande, le client choisit le retrait chez l'agriculteur ou la livraison à domicile (avec son adresse). En confirmant, l'agriculteur peut indiquer la date prévue et les frais de livraison, envoyés au client par SMS.

**Messagerie** : chaque commande a sa discussion entre le client et l'agriculteur (« 💬 Discuter »). Les numéros de téléphone et e-mails tapés dans les messages sont masqués automatiquement, pour que les échanges restent sur la plateforme. Les messages non lus apparaissent dans les notifications.

**Prix du marché** (`/prix-du-marche`) : prix courant au kilo de chaque produit (médiane des annonces des 6 derniers mois exprimées en « / kg » ou « / tonne », dès 2 annonces), affiché aussi dans le catalogue à côté de chaque annonce.

**Wolof** : le lien « 🌍 Wolof / Français » du menu change la langue. Les traductions sont dans `langues.py` (dictionnaire français → wolof, à faire relire par un locuteur natif) ; dans les templates, un texte se traduit avec `{{ "Texte" | t }}` et reste en français s'il n'a pas de traduction.

**Annonces partageables** : chaque récolte a une page publique `/annonce/<id>` (sans compte, sans coordonnées), avec aperçu pour WhatsApp/Facebook (titre, prix, photo). L'agriculteur la partage avec le bouton « 📤 Partager sur WhatsApp » ; un visiteur qui s'inscrit depuis l'annonce revient directement sur la commande.

**Alertes produits** (`/mes-alertes`, clients) : « préviens-moi quand il y a du mil à Thiès » (10 alertes maximum). À chaque nouvelle récolte publiée, les clients dont une alerte correspond (même produit, localité facultative) reçoivent un e-mail et un SMS avec le lien de l'annonce.

**Pré-commandes** : une récolte dont la date de disponibilité est future (jusqu'à un an) apparaît « 🌱 À venir » et se réserve dès maintenant ; filtre « Disponible maintenant / À venir » dans le catalogue, mention « Pré-commande » dans les commandes du client et de l'agriculteur.

**Vitrine publique** : la page d'accueil montre les dernières récoltes et des boutons « Je vends / J'achète » ; le catalogue (`/catalogue`) et les prix du marché sont visibles sans compte ; `robots.txt` et `sitemap.xml` aident Google à référencer les annonces.

**Alertes SMS** : l'agriculteur reçoit un SMS à chaque nouvelle commande ou annulation, le client à chaque changement de statut (confirmée, livrée, annulée), si un téléphone est renseigné dans son profil. Crée une application sur [Orange Developer](https://developer.orange.com) avec l'API « SMS Moyen-Orient et Afrique » (pays : Sénégal), achète un pack de SMS, puis définis `ORANGE_SMS_CLIENT_ID`, `ORANGE_SMS_CLIENT_SECRET` et `ORANGE_SMS_EXPEDITEUR` (en général `2210000`, sauf numéro dédié fourni par Orange). Sans ces variables, les SMS s'affichent dans la console ; un SMS en échec ne bloque jamais la commande.

## Revenus : commission et Premium

- **Commission** : quand l'agriculteur marque une commande « livrée », il indique le montant encaissé ; la plateforme calcule sa commission (`TAUX_COMMISSION`, 5 % par défaut). L'agriculteur voit ce qu'il doit et le numéro où payer.
- **Premium** (`PRIX_PREMIUM_MENSUEL` FCFA pour 30 jours) : badge ⭐ Pro, annonces en tête du catalogue, et accès au financement (publier une demande, contacter un organisme). L'utilisateur paie par Wave / Orange Money au `NUMERO_PAIEMENT` puis déclare la référence sur `/premium`.
- **Paiement Wave** : avec `WAVE_API_KEY` (clé d'un compte Wave Business autorisée pour l'API Checkout), un bouton « Payer avec Wave » active le Premium et règle les commissions automatiquement : le site vérifie auprès de Wave que la session est payée (au retour de l'utilisateur, ou à sa prochaine visite) avant d'appliquer le paiement, une seule fois. Sans clé, le paiement manuel reste proposé.
- **Paiement des commandes via Wave** (au choix du client, si `WAVE_API_KEY` est définie) : l'agriculteur fixe le prix en confirmant, le client paie la plateforme avec Wave, la commission est retenue d'office ; après livraison, l'admin reverse le reste à l'agriculteur (ou rembourse le client si la commande est annulée) puis le marque dans `/admin`.
- **Statistiques agriculteur** (`/espace-agriculteur/statistiques`) : chiffre d'affaires, commandes par statut, taux d'acceptation et note pour tous ; ventes des 12 derniers mois et produits les plus demandés pour les membres Premium.
- **Comptabilité** (`/admin/export`) : revenus de la plateforme par mois (commissions réglées + Premium) et export Excel/CSV des ventes, commissions, reversements et abonnements, par année.
- **Parrainage** (`/parrainage`) : chaque utilisateur a un lien d'invitation. Quand un filleul réalise sa première vente ou son premier achat (livré, ≥ 5 000 FCFA, commission réglée, sans que le parrain soit l'acheteur ou le vendeur), le parrain reçoit 1 mois de Premium (6 au plus par an).
- **Administration** (`/admin`, réservé aux emails de `ADMIN_EMAILS`, une fois l'adresse confirmée par le lien reçu par e-mail : « Mon profil » > « Recevoir le lien de confirmation ») : valider les paiements Premium, marquer les commissions réglées, voir les revenus.

## Organisation du code

- `app.py` : point d'entrée (`python app.py` en local, `gunicorn app:app` en ligne).
- `core.py` : création de l'application, configuration, validation des prix/quantités et des photos.
- `database.py` : connexion SQLite (local) ou PostgreSQL (en ligne) et création des tables.
- `routes/` : les pages, regroupées par espace (`comptes`, `client`, `agriculteur`, `fournisseur`, `financement`, `notifications`).

## Vérifications

```powershell
python -m pytest
python -m compileall -q app.py core.py database.py emails.py sms.py wave.py prix_marche.py langues.py routes
```

Ces vérifications tournent aussi automatiquement sur GitHub (onglet *Actions*) à chaque pull request et à chaque mise à jour de `main`. Les contrôles automatiques couvrent les règles de saisie principales. Avant chaque mise en ligne, teste également manuellement l'inscription, les quatre rôles, l'ajout au panier et le changement de statut d'une commande.
