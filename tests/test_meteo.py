import pytest

import database
import meteo
from app import app

BRUT = {
    "time": [f"2026-10-{d:02d}" for d in range(14, 21)],
    "weathercode": [0, 1, 63, 95, 3, 0, 0],
    "temperature_2m_max": [36, 39.4, 31, 30, 33, 35, 36],
    "temperature_2m_min": [24, 25, 22, 22, 23, 24, 24],
    "precipitation_sum": [0, 0, 12.3, 20, 0, 0, None],
    "precipitation_probability_max": [0, 5, 90, 95, 10, 0, None],
    "windspeed_10m_max": [12, 15, 25, 45, 10, 8, 9],
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    monkeypatch.setattr(meteo, "_cache", {})
    appels = []
    monkeypatch.setattr(meteo, "_telecharger", lambda lat, lon: appels.append((lat, lon)) or BRUT)
    connexion = database.get_connexion()
    connexion.execute("INSERT INTO utilisateurs (nom, email, mot_de_passe, role) VALUES ('Fatou', 'f@x.sn', 'x', 'agriculteur')")
    connexion.execute("""INSERT INTO recoltes (agriculteur_id, nom, quantite, prix, date_disponibilite, localite)
                         VALUES (1, 'Mil', '100 kg', '500 FCFA / kg', '2026-01-01', 'Thiès')""")
    connexion.commit()
    connexion.close()
    client = app.test_client()
    client.appels = appels
    with client.session_transaction() as session:
        session.update(utilisateur_id=1, nom="Fatou", role="agriculteur")
    return client


def test_meteo_de_la_localite_de_l_agriculteur_et_conseils(client):
    page = client.get("/espace-agriculteur/meteo").get_data(as_text=True)
    assert "7 prochains jours à Thiès" in page
    assert "Pluie attendue ven. 16 (12.3 mm)" in page and "Fortes chaleurs" in page and "Vent fort" in page
    client.get("/espace-agriculteur/meteo")
    assert len(client.appels) == 1  # en cache


def test_resume_sur_l_espace_et_localite_inconnue(client):
    assert "Météo à Thiès" in client.get("/espace-agriculteur/meteo/resume").get_data(as_text=True)
    assert "meteo-resume" in client.get("/espace-agriculteur").get_data(as_text=True)
    page = client.get("/espace-agriculteur/meteo?lieu=Village inconnu").get_data(as_text=True)
    assert "inconnue" in page


def test_panne_du_service(client, monkeypatch):
    def panne(lat, lon):
        raise OSError("réseau")
    monkeypatch.setattr(meteo, "_telecharger", panne)
    assert client.get("/espace-agriculteur/meteo/resume").status_code == 204
    assert "indisponible" in client.get("/espace-agriculteur/meteo").get_data(as_text=True)
