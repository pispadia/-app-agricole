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
    import psycopg2.pool
    # Render fournit parfois une URL commençant par "postgres://", que psycopg2
    # n'accepte plus depuis SQLAlchemy 1.4+ ; on la corrige en "postgresql://".
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Colonne identifiant auto-incrémentée : syntaxe différente entre SQLite et PostgreSQL
ID_AUTO = "SERIAL PRIMARY KEY" if UTILISE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"


# Colonnes des listes de récoltes et de produits, sans la photo (stockée en base64, elle
# pèse jusqu'à 2 Mo) : les pages l'affichent via /annonce/<id>/photo ou /produit/<id>/photo.
COLONNES_RECOLTE = """recoltes.id, recoltes.agriculteur_id, recoltes.nom, recoltes.quantite, recoltes.prix,
    recoltes.prix_gros, recoltes.quantite_gros_min, recoltes.date_disponibilite, recoltes.localite,
    recoltes.description, recoltes.statut, recoltes.date_creation, recoltes.masquee,
    (recoltes.photo IS NOT NULL) AS a_photo"""
COLONNES_PRODUIT = """produits_fournisseur.id, produits_fournisseur.fournisseur_id, produits_fournisseur.nom,
    produits_fournisseur.type_produit, produits_fournisseur.variete, produits_fournisseur.duree_croissance,
    produits_fournisseur.quantite, produits_fournisseur.prix, produits_fournisseur.localite,
    produits_fournisseur.description, produits_fournisseur.statut, produits_fournisseur.date_creation,
    (produits_fournisseur.photo IS NOT NULL) AS a_photo"""


class ConnexionCompatible:
    """
    Enveloppe une connexion SQLite ou PostgreSQL pour offrir la même interface
    simple dans tout le reste du code : connexion.execute(requete, parametres),
    connexion.commit(), connexion.close(). Ainsi, app.py n'a pas besoin de savoir
    quelle base de données est utilisée derrière.
    """

    def __init__(self, connexion_brute, depuis_reservoir=False):
        self._connexion = connexion_brute
        self._depuis_reservoir = depuis_reservoir
        self._fermee = False
        self._utilisee = False

    def execute(self, requete, parametres=()):
        if UTILISE_POSTGRES:
            requete = requete.replace("?", "%s")
        try:
            curseur = self._connexion.cursor()
            curseur.execute(requete, parametres)
        except (psycopg2.OperationalError, psycopg2.InterfaceError) if UTILISE_POSTGRES else ():
            # Connexion du réservoir coupée par le serveur pendant qu'elle attendait (ex : Supabase
            # ferme les connexions inactives). Si rien n'a encore été fait avec, on la remplace
            # et on rejoue la requête ; sinon l'erreur remonte (des écritures seraient perdues).
            if not (self._depuis_reservoir and not self._utilisee):
                raise
            curseur = self._reessayer_avec_connexion_neuve(requete, parametres)
        self._utilisee = True
        return curseur

    def _reessayer_avec_connexion_neuve(self, requete, parametres):
        # Plusieurs connexions inactives ont pu être coupées en même temps : on les écarte
        # une à une (au plus la taille du réservoir), puis on finit par une connexion neuve.
        for _ in range(int(os.environ.get("DB_POOL_MAX", "5")) + 1):
            if self._depuis_reservoir:
                _reservoir.putconn(self._connexion, close=True)
            else:
                self._connexion.close()
            self._connexion, self._depuis_reservoir = _connexion_postgres()
            try:
                curseur = self._connexion.cursor()
                curseur.execute(requete, parametres)
                return curseur
            except (psycopg2.OperationalError, psycopg2.InterfaceError):
                continue
        raise psycopg2.OperationalError("Base de données injoignable")

    def commit(self):
        self._connexion.commit()

    def rollback(self):
        self._connexion.rollback()

    def close(self):
        if self._fermee:
            return
        self._fermee = True
        if self._depuis_reservoir:
            # La connexion retourne dans le réservoir au lieu d'être fermée : la suivante
            # évite ainsi une nouvelle connexion chiffrée vers la base (lente).
            rendre_connexion(self._connexion)
        else:
            self._connexion.close()

    def __del__(self):
        # Filet de sécurité : une connexion oubliée (erreur avant close()) revient au réservoir
        try:
            self.close()
        except Exception:
            pass


# Réservoir de connexions PostgreSQL, créé au premier usage dans chaque processus
# (après le fork de gunicorn). DB_POOL_MAX limite les connexions par processus (au-delà,
# connexion directe), DB_POOL_MIN est le nombre gardé ouvert entre deux pages.
_reservoir = None


def _connexion_postgres():
    """Retourne (connexion, vient_du_reservoir)."""
    global _reservoir
    if _reservoir is None:
        # Une page utilise parfois 2 ou 3 connexions à la fois (la route, puis le menu) :
        # on en garde DB_POOL_MIN ouvertes au repos pour ne pas les rouvrir à chaque page.
        maximum = int(os.environ.get("DB_POOL_MAX", "5"))
        _reservoir = psycopg2.pool.ThreadedConnectionPool(
            min(int(os.environ.get("DB_POOL_MIN", "3")), maximum), maximum, DATABASE_URL,
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
    try:
        connexion = _reservoir.getconn()
        if connexion.closed:  # coupée par le serveur pendant qu'elle attendait : on la remplace
            _reservoir.putconn(connexion, close=True)
            connexion = _reservoir.getconn()
        return connexion, True
    except psycopg2.pool.PoolError:
        # Réservoir épuisé : connexion directe plutôt qu'une page en erreur
        return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor), False


def rendre_connexion(connexion):
    try:
        if not connexion.closed:
            connexion.rollback()  # termine toute transaction laissée ouverte
        _reservoir.putconn(connexion, close=bool(connexion.closed))
    except Exception:
        # Connexion inutilisable : on l'écarte, le réservoir en ouvrira une neuve
        _reservoir.putconn(connexion, close=True)


def get_connexion():
    """Ouvre une connexion à la base de données (PostgreSQL en ligne, SQLite en local)."""
    if UTILISE_POSTGRES:
        return ConnexionCompatible(*_connexion_postgres())
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


TABLES = (
    "utilisateurs", "recoltes", "commandes", "produits_fournisseur", "contacts_fournisseur",
    "offres_financement", "demandes_financement", "contacts_offre", "contacts_demande",
    "echecs_connexion", "paiements_premium", "paiements_wave", "avis", "messages_commande", "alertes_produit", "limites_envoi", "signalements",
    "photos_recolte",
)


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

    curseur = connexion.execute(f"""
        CREATE TABLE IF NOT EXISTS commandes (
            id {ID_AUTO},
            recolte_id INTEGER NOT NULL,
            client_id INTEGER NOT NULL,
            quantite_demandee TEXT NOT NULL,
            message TEXT,
            statut TEXT NOT NULL DEFAULT 'en_attente' CHECK(statut IN ('en_attente', 'confirmee', 'livree', 'annulee')),
            lu INTEGER NOT NULL DEFAULT 0,
            date_creation TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (recolte_id) REFERENCES recoltes (id),
            FOREIGN KEY (client_id) REFERENCES utilisateurs (id)
        )
    """)
    connexion.commit()

    curseur = connexion.execute(f"""
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

    curseur = connexion.execute(f"""
        CREATE TABLE IF NOT EXISTS contacts_fournisseur (
            id {ID_AUTO},
            produit_id INTEGER NOT NULL,
            agriculteur_id INTEGER NOT NULL,
            message TEXT,
            lu INTEGER NOT NULL DEFAULT 0,
            date_creation TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (produit_id) REFERENCES produits_fournisseur (id),
            FOREIGN KEY (agriculteur_id) REFERENCES utilisateurs (id)
        )
    """)

    curseur = connexion.execute(f"""
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

    curseur = connexion.execute(f"""
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

    curseur = connexion.execute(f"""
        CREATE TABLE IF NOT EXISTS contacts_offre (
            id {ID_AUTO},
            offre_id INTEGER NOT NULL,
            agriculteur_id INTEGER NOT NULL,
            message TEXT,
            lu INTEGER NOT NULL DEFAULT 0,
            date_creation TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (offre_id) REFERENCES offres_financement (id),
            FOREIGN KEY (agriculteur_id) REFERENCES utilisateurs (id)
        )
    """)

    curseur = connexion.execute(f"""
        CREATE TABLE IF NOT EXISTS contacts_demande (
            id {ID_AUTO},
            demande_id INTEGER NOT NULL,
            financeur_id INTEGER NOT NULL,
            message TEXT,
            lu INTEGER NOT NULL DEFAULT 0,
            date_creation TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (demande_id) REFERENCES demandes_financement (id),
            FOREIGN KEY (financeur_id) REFERENCES utilisateurs (id)
        )
    """)
    connexion.commit()

    # Échecs de connexion récents, pour bloquer temporairement un compte après
    # trop de mots de passe faux (instant = horodatage Unix en secondes)
    connexion.execute(f"""
        CREATE TABLE IF NOT EXISTS echecs_connexion (
            id {ID_AUTO},
            email TEXT NOT NULL,
            instant BIGINT NOT NULL
        )
    """)
    connexion.commit()

    # Paiements d'abonnement Premium déclarés par les utilisateurs (référence de la
    # transaction Wave / Orange Money), validés à la main par l'administrateur
    connexion.execute(f"""
        CREATE TABLE IF NOT EXISTS paiements_premium (
            id {ID_AUTO},
            utilisateur_id INTEGER NOT NULL,
            reference TEXT NOT NULL,
            montant INTEGER NOT NULL,
            statut TEXT NOT NULL DEFAULT 'en_attente' CHECK(statut IN ('en_attente', 'valide', 'refuse')),
            date_creation TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (utilisateur_id) REFERENCES utilisateurs (id)
        )
    """)
    connexion.commit()

    # Paiements Wave (abonnement Premium, commissions ou commande payée par le client) :
    # une ligne par session de paiement ; « details » liste les commandes concernées
    objets_paiement = "('premium', 'commission', 'commande')"
    table_paiements_wave = f"""
        CREATE TABLE IF NOT EXISTS paiements_wave (
            id {ID_AUTO},
            utilisateur_id INTEGER NOT NULL,
            objet TEXT NOT NULL CHECK(objet IN {objets_paiement}),
            montant INTEGER NOT NULL,
            details TEXT,
            session_id TEXT,
            statut TEXT NOT NULL DEFAULT 'en_attente' CHECK(statut IN ('en_attente', 'paye', 'echec')),
            date_creation TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (utilisateur_id) REFERENCES utilisateurs (id)
        )
    """
    connexion.execute(table_paiements_wave)
    connexion.commit()

    # Migration : bases créées quand seuls 'premium' et 'commission' étaient acceptés
    if UTILISE_POSTGRES:
        contrainte = connexion.execute(
            """SELECT pg_get_constraintdef(oid) AS definition FROM pg_constraint
               WHERE conname = 'paiements_wave_objet_check'"""
        ).fetchone()
        if contrainte and "commande" not in contrainte["definition"]:
            connexion.execute("ALTER TABLE paiements_wave DROP CONSTRAINT paiements_wave_objet_check")
            connexion.execute(f"ALTER TABLE paiements_wave ADD CONSTRAINT paiements_wave_objet_check "
                              f"CHECK (objet IN {objets_paiement})")
            connexion.commit()
    else:
        definition_table = connexion.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='paiements_wave'"
        ).fetchone()
        if "'commande'" not in definition_table[0]:
            connexion.execute("ALTER TABLE paiements_wave RENAME TO paiements_wave_ancien")
            connexion.execute(table_paiements_wave)
            connexion.execute("INSERT INTO paiements_wave SELECT * FROM paiements_wave_ancien")
            connexion.execute("DROP TABLE paiements_wave_ancien")
            connexion.commit()

    # Avis d'un client sur une commande livrée : un seul avis par commande
    connexion.execute(f"""
        CREATE TABLE IF NOT EXISTS avis (
            id {ID_AUTO},
            commande_id INTEGER NOT NULL UNIQUE,
            client_id INTEGER NOT NULL,
            agriculteur_id INTEGER NOT NULL,
            note INTEGER NOT NULL CHECK(note BETWEEN 1 AND 5),
            commentaire TEXT,
            date_creation TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (commande_id) REFERENCES commandes (id),
            FOREIGN KEY (client_id) REFERENCES utilisateurs (id),
            FOREIGN KEY (agriculteur_id) REFERENCES utilisateurs (id)
        )
    """)
    connexion.commit()

    # Messagerie entre le client et l'agriculteur d'une commande (sans échanger leurs numéros)
    connexion.execute(f"""
        CREATE TABLE IF NOT EXISTS messages_commande (
            id {ID_AUTO},
            commande_id INTEGER NOT NULL,
            auteur_id INTEGER NOT NULL,
            destinataire_id INTEGER NOT NULL,
            contenu TEXT NOT NULL,
            lu INTEGER NOT NULL DEFAULT 0,
            date_creation TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (commande_id) REFERENCES commandes (id),
            FOREIGN KEY (auteur_id) REFERENCES utilisateurs (id),
            FOREIGN KEY (destinataire_id) REFERENCES utilisateurs (id)
        )
    """)
    connexion.commit()

    # Alertes produits : un client est prévenu dès qu'une récolte correspondante est publiée
    connexion.execute(f"""
        CREATE TABLE IF NOT EXISTS alertes_produit (
            id {ID_AUTO},
            client_id INTEGER NOT NULL,
            produit TEXT NOT NULL,
            libelle TEXT NOT NULL,
            localite TEXT,
            date_creation TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (client_id) REFERENCES utilisateurs (id)
        )
    """)
    connexion.commit()

    # Limites d'envoi (e-mails de réinitialisation, de confirmation, inscriptions) : une
    # ligne par envoi, pour bloquer les abus qui épuiseraient le quota d'e-mails
    connexion.execute(f"""
        CREATE TABLE IF NOT EXISTS limites_envoi (
            id {ID_AUTO},
            cle TEXT NOT NULL,
            instant INTEGER NOT NULL
        )
    """)
    connexion.commit()

    # Signalements d'annonces par les utilisateurs (un par personne et par annonce)
    connexion.execute(f"""
        CREATE TABLE IF NOT EXISTS signalements (
            id {ID_AUTO},
            recolte_id INTEGER NOT NULL,
            auteur_id INTEGER NOT NULL,
            motif TEXT NOT NULL,
            commentaire TEXT,
            statut TEXT NOT NULL DEFAULT 'ouvert',
            date_creation TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (recolte_id, auteur_id),
            FOREIGN KEY (recolte_id) REFERENCES recoltes (id),
            FOREIGN KEY (auteur_id) REFERENCES utilisateurs (id)
        )
    """)
    # Photos en plus de la photo principale (recoltes.photo), pour la galerie de l'annonce
    connexion.execute(f"""
        CREATE TABLE IF NOT EXISTS photos_recolte (
            id {ID_AUTO},
            recolte_id INTEGER NOT NULL,
            photo TEXT NOT NULL,
            FOREIGN KEY (recolte_id) REFERENCES recoltes (id)
        )
    """)
    connexion.commit()

    # En ligne (Supabase), active la protection RLS sur toutes les tables : l'API
    # publique de Supabase n'y a alors plus accès, l'application (propriétaire des
    # tables) continue de les utiliser normalement. Sans effet si déjà activée.
    if UTILISE_POSTGRES:
        for nom_table in TABLES:
            connexion.execute(f"ALTER TABLE {nom_table} ENABLE ROW LEVEL SECURITY")
        connexion.commit()

    # Colonnes ajoutées après coup (bases existantes, SQLite comme PostgreSQL) :
    # numéro de téléphone facultatif, et suivi des changements de statut vus par le client
    # (lu_client = 0 quand l'agriculteur a fait évoluer la commande).
    colonnes_ajoutees = (
        ("utilisateurs", "telephone", "TEXT"),
        ("commandes", "lu_client", "INTEGER NOT NULL DEFAULT 1"),
        # Premium : date de fin d'abonnement (AAAA-MM-JJ), vide si jamais abonné
        ("utilisateurs", "premium_jusqu_au", "TEXT"),
        # Revenus : montant de la vente saisi à la livraison et commission due à la plateforme
        ("commandes", "montant", "INTEGER"),
        ("commandes", "commission", "INTEGER"),
        ("commandes", "commission_payee", "INTEGER NOT NULL DEFAULT 0"),
        # Livraison : retrait chez l'agriculteur ou livraison à l'adresse indiquée ;
        # date prévue et frais fixés par l'agriculteur à la confirmation
        # Adresse e-mail confirmée par lien (vide tant que non confirmée) ; on garde
        # l'adresse et non un simple drapeau pour qu'un changement d'e-mail l'invalide
        ("utilisateurs", "email_confirme", "TEXT"),
        # Compte suspendu par un administrateur (fraude, contournement de la commission...)
        ("utilisateurs", "suspendu", "INTEGER NOT NULL DEFAULT 0"),
        # Parrainage : code d'invitation, parrain, et date de la récompense versée au parrain
        ("utilisateurs", "code_parrainage", "TEXT"),
        # Modération : annonce masquée (3 signalements, ou décision de l'admin)
        ("recoltes", "masquee", "INTEGER NOT NULL DEFAULT 0"),
        # Rappels automatiques (tâche quotidienne) : déjà envoyés, pour ne jamais les répéter
        ("commandes", "rappel_pret_envoye", "INTEGER NOT NULL DEFAULT 0"),
        ("commandes", "relance_envoyee", "INTEGER NOT NULL DEFAULT 0"),
        ("utilisateurs", "rappel_premium_pour", "TEXT"),
        ("utilisateurs", "parrain_id", "INTEGER"),
        ("utilisateurs", "parrainage_recompense_le", "TEXT"),
        ("commandes", "mode_livraison", "TEXT NOT NULL DEFAULT 'retrait'"),
        # Paiement : à la livraison, ou en ligne via Wave à la plateforme, qui garde sa
        # commission et reverse le reste à l'agriculteur (ou rembourse si la commande est annulée)
        ("commandes", "mode_paiement", "TEXT NOT NULL DEFAULT 'livraison'"),
        ("commandes", "montant_a_payer", "INTEGER"),
        ("commandes", "paye_en_ligne", "INTEGER NOT NULL DEFAULT 0"),
        ("commandes", "reverse_agriculteur", "INTEGER NOT NULL DEFAULT 0"),
        ("commandes", "rembourse", "INTEGER NOT NULL DEFAULT 0"),
        ("commandes", "adresse_livraison", "TEXT"),
        ("commandes", "date_livraison_prevue", "TEXT"),
        ("commandes", "frais_livraison", "INTEGER"),
        # Date d'inscription (statistiques de l'admin) ; vide pour les comptes plus anciens
        ("utilisateurs", "date_inscription", "TEXT"),
    )
    for nom_table, colonne, definition in colonnes_ajoutees:
        try:
            if colonne not in colonnes_de_table(curseur, nom_table):
                curseur.execute(f"ALTER TABLE {nom_table} ADD COLUMN {colonne} {definition}")
                connexion.commit()
        except Exception as erreur:
            connexion.rollback()
            print(f"[migration] ERREUR ajout {nom_table}.{colonne} : {erreur}")

    # Ajoute la colonne "lu" aux tables déjà existantes (SQLite comme PostgreSQL) créées
    # avant l'introduction des notifications
    for nom_table in ("commandes", "contacts_fournisseur", "contacts_offre", "contacts_demande"):
        try:
            colonnes_existantes = colonnes_de_table(curseur, nom_table)
            print(f"[migration] {nom_table} -> colonnes actuelles : {colonnes_existantes}")
            if "lu" not in colonnes_existantes:
                print(f"[migration] {nom_table} : ajout de la colonne lu...")
                curseur.execute(f"ALTER TABLE {nom_table} ADD COLUMN lu INTEGER NOT NULL DEFAULT 0")
                connexion.commit()
                print(f"[migration] {nom_table} : colonne lu ajoutée avec succès.")
            else:
                print(f"[migration] {nom_table} : colonne lu déjà présente, rien à faire.")
        except Exception as erreur:
            connexion.rollback()
            print(f"[migration] ERREUR sur {nom_table} : {erreur}")

    connexion.close()
    print(f"Base de données initialisée ({'PostgreSQL' if UTILISE_POSTGRES else 'SQLite'}).")


if __name__ == "__main__":
    init_db()
