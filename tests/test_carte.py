import json
import re

import pytest

import database
from app import app
from localites import coordonnees, LIEUX


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    connexion = database.get_connexion()
    connexion.execute("INSERT INTO utilisateurs (nom, email, mot_de_passe, role) VALUES ('Fatou', 'f@x.sn', 'x', 'agriculteur')")
    for nom, localite in (("Mil", "Thiès"), ("Oignon", "Potou, Louga"), ("Arachide", "thies ville"),
                          ("Mangue", "Mon village")):
        connexion.execute("""INSERT INTO recoltes (agriculteur_id, nom, quantite, prix, date_disponibilite, localite)
                             VALUES (1, ?, '100 kg', '500 FCFA / kg', '2026-01-01', ?)""", (nom, localite))
    connexion.commit()
    connexion.close()
    return app.test_client()


def test_coordonnees_des_localites():
    assert coordonnees("Thiès") == LIEUX["thies"]
    assert coordonnees("ST-LOUIS") == LIEUX["saint louis"]
    assert coordonnees("Potou, Louga") == LIEUX["potou"]  # premier lieu le plus précis cité
    assert coordonnees("Richard-Toll") == LIEUX["richard toll"]
    assert coordonnees("Keur Massar") == LIEUX["keur massar"]
    assert coordonnees("Mon village") is None and coordonnees("") is None


def test_carte_regroupe_les_annonces_par_lieu(client):
    page = client.get("/carte").get_data(as_text=True)
    points = json.loads(re.search(r"const points = (\[.*?\]);", page).group(1))
    par_lieu = {(p["lat"], p["lon"]): sorted(a["nom"] for a in p["annonces"]) for p in points}
    assert par_lieu[LIEUX["thies"]] == ["Arachide", "Mil"]
    assert par_lieu[LIEUX["potou"]] == ["Oignon"]
    assert "Autres localités" in page and "Mon village" in page
    assert 'href="/carte"' in client.get("/catalogue").get_data(as_text=True)
