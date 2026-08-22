import sqlite3

DB_NAME = "app_agricole.db"


def get_connexion():
    """Ouvre une connexion à la base de données."""
    connexion = sqlite3.connect(DB_NAME)
    connexion.row_factory = sqlite3.Row  # permet d'accéder aux colonnes par leur nom
    return connexion


def init_db():
    """Crée les tables si elles n'existent pas encore."""
    connexion = get_connexion()
    curseur = connexion.cursor()

    curseur.execute("""
        CREATE TABLE IF NOT EXISTS utilisateurs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            mot_de_passe TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('client', 'agriculteur', 'fournisseur'))
        )
    """)

    # Migration : ajoute le rôle 'financeur' si la table a été créée avant son introduction
    # (SQLite ne permet pas de modifier une contrainte CHECK directement, donc on recrée la table)
    definition_table = curseur.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='utilisateurs'"
    ).fetchone()
    if definition_table and "financeur" not in definition_table[0]:
        curseur.execute("ALTER TABLE utilisateurs RENAME TO utilisateurs_ancien")
        curseur.execute("""
            CREATE TABLE utilisateurs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nom TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                mot_de_passe TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('client', 'agriculteur', 'fournisseur', 'financeur'))
            )
        """)
        curseur.execute("INSERT INTO utilisateurs SELECT * FROM utilisateurs_ancien")
        curseur.execute("DROP TABLE utilisateurs_ancien")

    curseur.execute("""
        CREATE TABLE IF NOT EXISTS recoltes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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

    # Ajoute les colonnes aux bases déjà existantes (créées avant cette mise à jour)
    colonnes_existantes = [c[1] for c in curseur.execute("PRAGMA table_info(recoltes)").fetchall()]
    colonnes_a_ajouter = {
        "prix_gros": "TEXT",
        "quantite_gros_min": "TEXT",
        "statut": "TEXT NOT NULL DEFAULT 'disponible'",
    }
    for colonne, type_sql in colonnes_a_ajouter.items():
        if colonne not in colonnes_existantes:
            curseur.execute(f"ALTER TABLE recoltes ADD COLUMN {colonne} {type_sql}")

    curseur.execute("""
        CREATE TABLE IF NOT EXISTS commandes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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

    curseur.execute("""
        CREATE TABLE IF NOT EXISTS produits_fournisseur (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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

    curseur.execute("""
        CREATE TABLE IF NOT EXISTS contacts_fournisseur (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            produit_id INTEGER NOT NULL,
            agriculteur_id INTEGER NOT NULL,
            message TEXT,
            date_creation TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (produit_id) REFERENCES produits_fournisseur (id),
            FOREIGN KEY (agriculteur_id) REFERENCES utilisateurs (id)
        )
    """)

    curseur.execute("""
        CREATE TABLE IF NOT EXISTS offres_financement (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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

    curseur.execute("""
        CREATE TABLE IF NOT EXISTS demandes_financement (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agriculteur_id INTEGER NOT NULL,
            objet TEXT NOT NULL,
            montant_souhaite TEXT NOT NULL,
            description TEXT,
            statut TEXT NOT NULL DEFAULT 'ouverte' CHECK(statut IN ('ouverte', 'traitee')),
            date_creation TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (agriculteur_id) REFERENCES utilisateurs (id)
        )
    """)

    curseur.execute("""
        CREATE TABLE IF NOT EXISTS contacts_offre (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            offre_id INTEGER NOT NULL,
            agriculteur_id INTEGER NOT NULL,
            message TEXT,
            date_creation TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (offre_id) REFERENCES offres_financement (id),
            FOREIGN KEY (agriculteur_id) REFERENCES utilisateurs (id)
        )
    """)

    curseur.execute("""
        CREATE TABLE IF NOT EXISTS contacts_demande (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    print("Base de données initialisée.")


if __name__ == "__main__":
    init_db()
