import pytest

import database
from app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    connexion = database.get_connexion()
    for i in range(12):
        connexion.execute("INSERT INTO utilisateurs (nom, email, mot_de_passe, role) VALUES (?, ?, 'x', 'agriculteur')",
                          (f"Agri {i}", f"a{i}@x.sn"))
    connexion.execute("UPDATE utilisateurs SET suspendu = 1 WHERE id = 12")
    for agriculteur_id, nom in ((1, "Mil"), (2, "Oignon"), (12, "Arnaque")):
        connexion.execute(
            """INSERT INTO recoltes (agriculteur_id, nom, quantite, prix, date_disponibilite, localite)
               VALUES (?, ?, '100 kg', '500 FCFA / kg', '2026-01-01', 'Thiès')""", (agriculteur_id, nom))
    connexion.commit()
    connexion.close()
    return app.test_client()


def test_accueil_vitrine(client):
    page = client.get("/").get_data(as_text=True)
    assert "Mil" in page and "Oignon" in page and "Arnaque" not in page
    assert "<div class=\"tuile-valeur\">11</div>" in page  # agriculteurs non suspendus
    assert "/inscription?role=agriculteur" in page and "/catalogue" in page


def test_catalogue_public_sans_compte(client):
    page = client.get("/catalogue?recherche=oign").get_data(as_text=True)
    assert "Oignon" in page and ">Mil<" not in page and "/annonce/2" in page
    assert "Je vends mes récoltes" in page


def test_inscription_avec_role_propose(client):
    assert 'value="agriculteur" selected' in client.get("/inscription?role=agriculteur").get_data(as_text=True)
    assert "selected>" in client.get("/inscription?role=pirate").get_data(as_text=True)  # « Je suis... » par défaut


def test_prix_du_marche_public(client):
    assert client.get("/prix-du-marche").status_code == 200


def test_referencement(client):
    robots = client.get("/robots.txt").get_data(as_text=True)
    assert "Allow: /annonce/" in robots and "Disallow: /" in robots and "sitemap.xml" in robots
    plan = client.get("/sitemap.xml").get_data(as_text=True)
    assert "http://localhost/annonce/1" in plan and "http://localhost/annonce/3" not in plan
