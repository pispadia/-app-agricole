import os
import sqlite3

DB_NAME = "app_agricole.db"

# Sur Render, une base PostgreSQL fournit automatiquement la variable DATABASE_URL
# quand elle est liée au service. En local, cette variable n'existe pas, donc on
# utilise SQLite comme avant (aucun changement pour toi en développement).
DATABASE_URL = os.environ.get("DATABASE_URL")
UTILISE_POSTGRES = bool(DATABASE_URL)

if UTILISE_POSTGRES:
    import psycopg2
    import psycopg2.extras
    # Render fournit parfois une URL commençant par "postgres://", que psycopg2
    # n'accepte plus depuis SQLAlchemy 1.4+ ; on la corrige en "postgresql://".
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Colonne identifiant auto-incrémentée : syntaxe différente entre SQLite et PostgreSQL
ID_AUTO = "SERIAL PRIMARY KEY" if UTILISE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"


class ConnexionCompatible:
    """
    Enveloppe une connexion SQLite ou PostgreSQL pour offrir la même interface
    simple dans tout le reste du code : connexion.execute(requete, parametres),
    connexion.commit(), connexion.close(). Ainsi, app.py n'a pas besoin de savoir
    quelle base de données est utilisée derrière.
    """

    def __init__(self, connexion_brute):
        self._connexion = connexion_brute

    def execute(self, requete, parametres=()):
        curseur = self._connexion.cursor()
        if UTILISE_POSTGRES:
            requete = requete.replace("?", "%s")
        curseur.execute(requete, parametres)
        return curseur

    def commit(self):
        self._connexion.commit()

    def rollback(self):
        self._connexion.rollback()

    def close(self):
        self._connexion.close()


def get_connexion():
    """Ouvre une connexion à la base de données (PostgreSQL en ligne, SQLite en local)."""
    if UTILISE_POSTGRES:
        connexion_brute = psycopg2.connect(
            DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor
        )
    else:
        connexion_brute = sqlite3.connect(DB_NAME)
        connexion_brute.row_factory = sqlite3.Row
    return ConnexionCompatible(connexion_brute)


def colonnes_de_table(curseur, nom_table):
    """Retourne la liste des colonnes existantes d'une table, pour SQLite ou PostgreSQL."""
    if UTILISE_POSTGRES:
        curseur.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
            (nom_table,)
        )
        return [row["column_name"] for row in curseur.fetchall()]
    else:
        curseur.execute(f"PRAGMA table_info({nom_table})")
        return [row[1] for row in curseur.fetchall()]


def init_db():
    """Crée les tables si elles n'existent pas encore."""
    connexion = get_connexion()
    curseur = connexion.execute(f"""
        CREATE TABLE IF NOT EXISTS utilisateurs (
            id {ID_AUTO},
            nom TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            mot_de_passe TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('client', 'agriculteur', 'fournisseur', 'financeur'))
        )
    """)
    connexion.commit()

    # Migration : ajoute le rôle 'financeur' aux bases SQLite locales créées avant
    # son introduction (une base PostgreSQL toute neuve a déjà la bonne contrainte).
    if not UTILISE_POSTGRES:
        definition_table = curseur.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='utilisateurs'"
        ).fetchone()
        if definition_table and "financeur" not in definition_table[0]:
            curseur.execute("ALTER TABLE utilisateurs RENAME TO utilisateurs_ancien")
            curseur.execute(f"""
                CREATE TABLE utilisateurs (
                    id {ID_AUTO},
                    nom TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    mot_de_passe TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('client', 'agriculteur', 'fournisseur', 'financeur'))
                )
            """)
            curseur.execute("INSERT INTO utilisateurs SELECT * FROM utilisateurs_ancien")
            curseur.execute("DROP TABLE utilisateurs_ancien")
            connexion.commit()

    curseur = connexion.execute(f"""
        CREATE TABLE IF NOT EXISTS recoltes (
            id {ID_AUTO},
            agriculteur_id INTEGER NOT NULL,
            nom TEXT NOT NULL,
            quantite TEXT NOT NULL,
            prix TEXT NOT NULL,
            prix_gros TEXT,
            quantite_gros_min TEXT,
            date_disponibilite TEXT NOT NULL,
            localite TEXT NOT NULL,
            description TEXT,
            photo TEXT,
            statut TEXT NOT NULL DEFAULT 'disponible' CHECK(statut IN ('disponible', 'epuise')),
            date_creation TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (agriculteur_id) REFERENCES utilisateurs (id)
        )
    """)
    connexion.commit()

    # Ajoute les colonnes aux bases SQLite locales déjà existantes (créées avant cette mise à jour)
    if not UTILISE_POSTGRES:
        colonnes_existantes = colonnes_de_table(curseur, "recoltes")
        colonnes_a_ajouter = {
            "prix_gros": "TEXT",
            "quantite_gros_min": "TEXT",
            "statut": "TEXT NOT NULL DEFAULT 'disponible'",
        }
        for colonne, type_sql in colonnes_a_ajouter.items():
            if colonne not in colonnes_existantes:
                curseur.execute(f"ALTER TABLE recoltes ADD COLUMN {colonne} {type_sql}")
        connexion.commit()

    connexion.execute(f"""
        CREATE TABLE IF NOT EXISTS commandes (
            id {ID_AUTO},
            recolte_id INTEGER NOT NULL,
            client_id INTEGER NOT NULL,
            quantite_demandee TEXT NOT NULL,
            message TEXT,
            statut TEXT NOT NULL DEFAULT 'en_attente' CHECK(statut IN ('en_attente', 'confirmee', 'livree', 'annulee')),
            date_creation TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (recolte_id) REFERENCES recoltes (id),
            FOREIGN KEY (client_id) REFERENCES utilisateurs (id)
        )
    """)

    connexion.execute(f"""
        CREATE TABLE IF NOT EXISTS produits_fournisseur (
            id {ID_AUTO},
            fournisseur_id INTEGER NOT NULL,
            nom TEXT NOT NULL,
            type_produit TEXT NOT NULL CHECK(type_produit IN ('semence', 'pepiniere')),
            variete TEXT,
            duree_croissance TEXT,
            quantite TEXT NOT NULL,
            prix TEXT NOT NULL,
            localite TEXT NOT NULL,
            description TEXT,
            photo TEXT,
            statut TEXT NOT NULL DEFAULT 'disponible' CHECK(statut IN ('disponible', 'epuise')),
            date_creation TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (fournisseur_id) REFERENCES utilisateurs (id)
        )
    """)

    connexion.execute(f"""
        CREATE TABLE IF NOT EXISTS contacts_fournisseur (
            id {ID_AUTO},
            produit_id INTEGER NOT NULL,
            agriculteur_id INTEGER NOT NULL,
            message TEXT,
            date_creation TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (produit_id) REFERENCES produits_fournisseur (id),
            FOREIGN KEY (agriculteur_id) REFERENCES utilisateurs (id)
        )
    """)

    connexion.execute(f"""
        CREATE TABLE IF NOT EXISTS offres_financement (
            id {ID_AUTO},
            financeur_id INTEGER NOT NULL,
            nom TEXT NOT NULL,
            type_financement TEXT NOT NULL CHECK(type_financement IN ('pret', 'subvention', 'investissement')),
            montant TEXT NOT NULL,
            taux_conditions TEXT,
            duree TEXT,
            description TEXT,
            statut TEXT NOT NULL DEFAULT 'active' CHECK(statut IN ('active', 'fermee')),
            date_creation TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (financeur_id) REFERENCES utilisateurs (id)
        )
    """)

    connexion.execute(f"""
        CREATE TABLE IF NOT EXISTS demandes_financement (
            id {ID_AUTO},
            agriculteur_id INTEGER NOT NULL,
            objet TEXT NOT NULL,
            montant_souhaite TEXT NOT NULL,
            description TEXT,
            statut TEXT NOT NULL DEFAULT 'ouverte' CHECK(statut IN ('ouverte', 'traitee')),
            date_creation TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (agriculteur_id) REFERENCES utilisateurs (id)
        )
    """)

    connexion.execute(f"""
        CREATE TABLE IF NOT EXISTS contacts_offre (
            id {ID_AUTO},
            offre_id INTEGER NOT NULL,
            agriculteur_id INTEGER NOT NULL,
            message TEXT,
            date_creation TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (offre_id) REFERENCES offres_financement (id),
            FOREIGN KEY (agriculteur_id) REFERENCES utilisateurs (id)
        )
    """)

    connexion.execute(f"""
        CREATE TABLE IF NOT EXISTS contacts_demande (
            id {ID_AUTO},
            demande_id INTEGER NOT NULL,
            financeur_id INTEGER NOT NULL,
            message TEXT,
            date_creation TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (demande_id) REFERENCES demandes_financement (id),
            FOREIGN KEY (financeur_id) REFERENCES utilisateurs (id)
        )
    """)

    connexion.commit()
    connexion.close()
    print(f"Base de données initialisée ({'PostgreSQL' if UTILISE_POSTGRES else 'SQLite'}).")


if __name__ == "__main__":
    init_db()
