# App Agricole

Plateforme locale qui relie agriculteurs, clients, fournisseurs de semences et financeurs.

## Lancer en local

```powershell
python -m pip install -r requirements.txt
python app.py
```

Ouvre ensuite `http://127.0.0.1:5000`.

## Configuration de production

Copie `.env.example` dans les variables d'environnement de l'hébergeur, puis définis une valeur `SECRET_KEY` longue et aléatoire. Ne lance jamais l'application avec le débogage Flask activé en production. Une URL PostgreSQL peut être fournie avec `DATABASE_URL`; SQLite reste utilisé localement.

## Vérifications

```powershell
python -m pytest
python -m py_compile app.py database.py
```

Les contrôles automatiques couvrent les règles de saisie principales. Avant chaque mise en ligne, teste également manuellement l'inscription, les quatre rôles, l'ajout au panier et le changement de statut d'une commande.
