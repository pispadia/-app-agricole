"""Point d'entrée de l'application (gunicorn app:app, ou python app.py en local)."""
from core import app, encoder_photo, prix_valide, quantite_valide  # noqa: F401
import routes  # noqa: F401  (enregistre toutes les routes sur app)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
