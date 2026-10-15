import base64

import pytest

import database
from app import app

LIEU = {"pays": "SN", "region": "Dakar", "departement": "Dakar", "commune": "Yoff"}  # adresse demandée à l'inscription

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
    assert "Créer un compte pour réserver" in page  # récolte du 01/11/2026 : à venir
    assert "f@x.sn" not in page  # aucune coordonnée


def test_photo_servie_comme_image(client):
    reponse = client.get("/annonce/1/photo")
    assert reponse.mimetype == "image/png" and reponse.data == PNG
    assert "max-age" in reponse.headers["Cache-Control"]
    # Deuxième visite : le navigateur envoie l'empreinte, la photo n'est pas renvoyée
    assert client.get("/annonce/1/photo", headers={"If-None-Match": reponse.headers["ETag"]}).status_code == 304
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
    client.post("/inscription", data={**LIEU, "nom": "Awa", "email": "a@x.sn", "mot_de_passe": "motdepasse", "role": "client"})
    reponse = client.post("/connexion", data={"email": "a@x.sn", "mot_de_passe": "motdepasse"})
    assert reponse.headers["Location"].endswith("/commander/1")


@pytest.mark.parametrize("suivant", ["https://pirate.example", "//pirate.example", "/\\pirate.example"])
def test_pas_de_redirection_externe(client, suivant):
    client.post("/inscription", data={**LIEU, "nom": "Awa", "email": "a@x.sn", "mot_de_passe": "motdepasse", "role": "client"})
    client.get("/connexion", query_string={"suivant": suivant})
    reponse = client.post("/connexion", data={"email": "a@x.sn", "mot_de_passe": "motdepasse"})
    assert reponse.headers["Location"].endswith("/espace-client")


def test_bouton_partager_pour_l_agriculteur(client):
    with client.session_transaction() as session:
        session.update(utilisateur_id=1, nom="Fatou", role="agriculteur")
    page = client.get("/espace-agriculteur").get_data(as_text=True)
    assert "https://wa.me/?text=Mil%20disponible%20%C3%A0%20Thi%C3%A8s" in page
    assert "http%3A//localhost/annonce/1" in page


def test_catalogue_leger_sans_photo_integree(client):
    with client.session_transaction() as session:
        session.update(utilisateur_id=1, nom="F", role="client")
    page = client.get("/espace-client").get_data(as_text=True)
    assert 'src="/annonce/1/photo"' in page and "base64" not in page


def test_page_404_propre(client):
    reponse = client.get("/annonce/99")
    assert reponse.status_code == 404 and "Page introuvable" in reponse.get_data(as_text=True)


def test_page_500_propre(client, monkeypatch):
    from routes import annonces

    def panne(*args):
        raise RuntimeError("base indisponible")

    monkeypatch.setattr(annonces, "recolte_publique", panne)
    monkeypatch.setitem(app.config, "PROPAGATE_EXCEPTIONS", False)
    reponse = client.get("/annonce/1")
    assert reponse.status_code == 500 and "Un problème est survenu" in reponse.get_data(as_text=True)
    assert "base indisponible" not in reponse.get_data(as_text=True)


def photo_envoyee(nom="p.png"):
    import io
    return (io.BytesIO(PNG), nom)


def connecter_agriculteur(client):
    with client.session_transaction() as s:
        s["utilisateur_id"] = 1
        s["role"] = "agriculteur"
        s["nom"] = "Fatou"


def nb_photos_supplementaires():
    connexion = database.get_connexion()
    n = connexion.execute("SELECT COUNT(*) AS n FROM photos_recolte WHERE recolte_id = 1").fetchone()["n"]
    connexion.close()
    return n


def formulaire_modification(**extra):
    return {"nom": "Mil", "quantite": "100 kg", "prix": "500 FCFA / kg", "date_disponibilite": "2026-11-01",
            "localite": "Thiès", "statut": "disponible", **extra}


def test_galerie_de_plusieurs_photos(client):
    connecter_agriculteur(client)
    client.post("/espace-agriculteur/modifier-recolte/1", content_type="multipart/form-data",
                data=formulaire_modification(photos_supplementaires=[photo_envoyee(), photo_envoyee()]))
    assert nb_photos_supplementaires() == 2

    page = client.get("/annonce/1").get_data(as_text=True)
    assert "📷 3 photos" in page
    assert page.count('src="/annonce/1/photo') == 3
    connexion = database.get_connexion()
    photo_id = connexion.execute("SELECT id FROM photos_recolte ORDER BY id").fetchone()["id"]
    connexion.close()
    reponse = client.get(f"/annonce/1/photo/{photo_id}")
    assert reponse.mimetype == "image/png" and reponse.data == PNG
    # La photo n'est pas accessible via une autre annonce
    assert client.get(f"/annonce/2/photo/{photo_id}").status_code == 404


def test_quatre_photos_maximum_et_suppression(client):
    connecter_agriculteur(client)
    client.post("/espace-agriculteur/modifier-recolte/1", content_type="multipart/form-data",
                data=formulaire_modification(photos_supplementaires=[photo_envoyee() for _ in range(5)]))
    assert nb_photos_supplementaires() == 3  # + la photo principale = 4

    connexion = database.get_connexion()
    photo_id = connexion.execute("SELECT id FROM photos_recolte ORDER BY id").fetchone()["id"]
    connexion.close()
    client.post("/espace-agriculteur/modifier-recolte/1", content_type="multipart/form-data",
                data=formulaire_modification(supprimer_photo=str(photo_id)))
    assert nb_photos_supplementaires() == 2
    assert client.get(f"/annonce/1/photo/{photo_id}").status_code == 404


def test_un_autre_agriculteur_ne_supprime_pas_les_photos(client):
    connexion = database.get_connexion()
    connexion.execute("INSERT INTO utilisateurs (nom, email, mot_de_passe, role) VALUES ('Awa', 'a@x.sn', 'x', 'agriculteur')")
    connexion.execute("INSERT INTO photos_recolte (recolte_id, photo) VALUES (1, 'data:image/png;base64,AA==')")
    connexion.commit()
    connexion.close()
    with client.session_transaction() as s:
        s["utilisateur_id"] = 2
        s["role"] = "agriculteur"
    client.post("/espace-agriculteur/modifier-recolte/1", content_type="multipart/form-data",
                data=formulaire_modification(supprimer_photo="1"))
    assert nb_photos_supplementaires() == 1


def test_publication_avec_plusieurs_photos(client):
    connecter_agriculteur(client)
    client.post("/espace-agriculteur/nouvelle-recolte", content_type="multipart/form-data",
                data={"nom": "Arachide", "quantite": "50 kg", "prix": "600 FCFA / kg",
                      "date_disponibilite": "2026-11-01", "localite": "Kaolack",
                      "photo": photo_envoyee(), "photos_supplementaires": [photo_envoyee(), photo_envoyee()]})
    connexion = database.get_connexion()
    n = connexion.execute("SELECT COUNT(*) AS n FROM photos_recolte WHERE recolte_id = 2").fetchone()["n"]
    connexion.close()
    assert n == 2


def test_publication_envoyee_apres_coupure_reseau_repond_en_json(client):
    connecter_agriculteur(client)
    entete = {"X-Hors-Ligne": "1"}
    reponse = client.post("/espace-agriculteur/nouvelle-recolte", headers=entete, content_type="multipart/form-data",
                          data={"nom": "Niébé", "quantite": "80 kg", "prix": "700 FCFA / kg",
                                "date_disponibilite": "2026-10-01", "localite": "Louga", "photo": photo_envoyee()})
    assert reponse.status_code == 200 and reponse.get_json()["ok"] is True
    reponse = client.post("/espace-agriculteur/nouvelle-recolte", headers=entete,
                          data={"nom": "Niébé", "quantite": "beaucoup", "prix": "700 FCFA / kg",
                                "date_disponibilite": "2026-10-01", "localite": "Louga"})
    assert reponse.status_code == 400 and "quantité" in reponse.get_json()["erreur"]
    with client.session_transaction() as session:
        session.clear()
    assert client.post("/espace-agriculteur/nouvelle-recolte", headers=entete, data={}).status_code == 401
