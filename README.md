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

## Revenus : commission et Premium

- **Commission** : quand l'agriculteur marque une commande « livrée », il indique le montant encaissé ; la plateforme calcule sa commission (`TAUX_COMMISSION`, 5 % par défaut). L'agriculteur voit ce qu'il doit et le numéro où payer.
- **Premium** (`PRIX_PREMIUM_MENSUEL` FCFA pour 30 jours) : badge ⭐ Pro, annonces en tête du catalogue, et accès au financement (publier une demande, contacter un organisme). L'utilisateur paie par Wave / Orange Money au `NUMERO_PAIEMENT` puis déclare la référence sur `/premium`.
- **Administration** (`/admin`, réservé aux emails de `ADMIN_EMAILS`) : valider les paiements Premium, marquer les commissions réglées, voir les revenus.

## Organisation du code

- `app.py` : point d'entrée (`python app.py` en local, `gunicorn app:app` en ligne).
- `core.py` : création de l'application, configuration, validation des prix/quantités et des photos.
- `database.py` : connexion SQLite (local) ou PostgreSQL (en ligne) et création des tables.
- `routes/` : les pages, regroupées par espace (`comptes`, `client`, `agriculteur`, `fournisseur`, `financement`, `notifications`).

## Vérifications

```powershell
python -m pytest
python -m compileall -q app.py core.py database.py emails.py routes
```

Ces vérifications tournent aussi automatiquement sur GitHub (onglet *Actions*) à chaque pull request et à chaque mise à jour de `main`. Les contrôles automatiques couvrent les règles de saisie principales. Avant chaque mise en ligne, teste également manuellement l'inscription, les quatre rôles, l'ajout au panier et le changement de statut d'une commande.
