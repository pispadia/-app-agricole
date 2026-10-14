"""Routes de l'application, regroupées par espace. Les importer les enregistre sur `app`."""
import langues  # noqa: F401  (filtre de traduction « t » et choix de la langue)
from routes import comptes, client, agriculteur, fournisseur, financement, notifications, premium, paiements_wave, avis, pwa, messagerie, admin_comptes, marche, annonces, alertes, statistiques, export, parrainage, vitrine, moderation, taches  # noqa: F401
