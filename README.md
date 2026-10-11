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

## Organisation du code

- `app.py` : point d'entrée (`python app.py` en local, `gunicorn app:app` en ligne).
- `core.py` : création de l'application, configuration, validation des prix/quantités et des photos.
- `database.py` : connexion SQLite (local) ou PostgreSQL (en ligne) et création des tables.
- `routes/` : les pages, regroupées par espace (`comptes`, `client`, `agriculteur`, `fournisseur`, `financement`, `notifications`).

## Vérifications

```powershell
python -m pytest
python -m compileall -q app.py core.py database.py routes
```

Ces vérifications tournent aussi automatiquement sur GitHub (onglet *Actions*) à chaque pull request et à chaque mise à jour de `main`. Les contrôles automatiques couvrent les règles de saisie principales. Avant chaque mise en ligne, teste également manuellement l'inscription, les quatre rôles, l'ajout au panier et le changement de statut d'une commande.
