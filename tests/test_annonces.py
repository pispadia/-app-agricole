import base64

import pytest

import database
from app import app

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    connexion = database.get_connexion()
    connexion.execute("INSERT INTO utilisateurs (nom, email, mot_de_passe, role) VALUES ('Fatou', 'f@x.sn', 'x', 'agriculteur')")
    photo = "data:image/png;base64," + base64.b64encode(PNG).decode()
    connexion.execute(
        """INSERT INTO recoltes (agriculteur_id, nom, quantite, prix, date_disponibilite, localite, photo)
           VALUES (1, 'Mil', '100 kg', '500 FCFA / kg', '2026-11-01', 'Thiès', ?)""", (photo,))
    connexion.commit()
    connexion.close()
    return app.test_client()


def test_annonce_publique_sans_compte(client):
    page = client.get("/annonce/1").get_data(as_text=True)
    assert "Mil" in page and "500 FCFA / kg" in page and "Fatou" in page
    assert 'property="og:title" content="Mil — 500 FCFA / kg (Thiès)"' in page
    assert 'property="og:image" content="http://localhost/annonce/1/photo"' in page
    assert "Créer un compte pour commander" in page
    assert "f@x.sn" not in page  # aucune coordonnée


def test_photo_servie_comme_image(client):
    reponse = client.get("/annonce/1/photo")
    assert reponse.mimetype == "image/png" and reponse.data == PNG
    assert "max-age" in reponse.headers["Cache-Control"]
    assert client.get("/annonce/99/photo").status_code == 404


def test_annonce_inconnue_ou_agriculteur_suspendu(client):
    assert client.get("/annonce/99").status_code == 404
    connexion = database.get_connexion()
    connexion.execute("UPDATE utilisateurs SET suspendu = 1 WHERE id = 1")
    connexion.commit()
    connexion.close()
    assert client.get("/annonce/1").status_code == 404


def test_inscription_puis_connexion_ramene_a_la_commande(client):
    client.get("/inscription?suivant=/commander/1")
    client.post("/inscription", data={"nom": "Awa", "email": "a@x.sn", "mot_de_passe": "motdepasse", "role": "client"})
    reponse = client.post("/connexion", data={"email": "a@x.sn", "mot_de_passe": "motdepasse"})
    assert reponse.headers["Location"].endswith("/commander/1")


@pytest.mark.parametrize("suivant", ["https://pirate.example", "//pirate.example", "/\\pirate.example"])
def test_pas_de_redirection_externe(client, suivant):
    client.post("/inscription", data={"nom": "Awa", "email": "a@x.sn", "mot_de_passe": "motdepasse", "role": "client"})
    client.get("/connexion", query_string={"suivant": suivant})
    reponse = client.post("/connexion", data={"email": "a@x.sn", "mot_de_passe": "motdepasse"})
    assert reponse.headers["Location"].endswith("/espace-client")


def test_bouton_partager_pour_l_agriculteur(client):
    with client.session_transaction() as session:
        session.update(utilisateur_id=1, nom="Fatou", role="agriculteur")
    page = client.get("/espace-agriculteur").get_data(as_text=True)
    assert "https://wa.me/?text=Mil%20disponible%20%C3%A0%20Thi%C3%A8s" in page
    assert "http%3A//localhost/annonce/1" in page
