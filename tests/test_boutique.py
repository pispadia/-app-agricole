import pytest

import database
from app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    connexion = database.get_connexion()
    for nom, email, role in (("Fatou Sarr", "f@x.sn", "agriculteur"), ("Awa", "a@x.sn", "client")):
        connexion.execute("INSERT INTO utilisateurs (nom, email, mot_de_passe, role) VALUES (?, ?, 'x', ?)",
                          (nom, email, role))
    for nom, statut, masquee in (("Mil souna", "disponible", 0), ("Arachide", "epuise", 0), ("Niébé", "disponible", 1)):
        connexion.execute(
            """INSERT INTO recoltes (agriculteur_id, nom, quantite, prix, date_disponibilite, localite, statut, masquee)
               VALUES (1, ?, '100 kg', '500 FCFA / kg', '2026-01-01', 'Thiès', ?, ?)""", (nom, statut, masquee))
    connexion.commit()
    connexion.close()
    return app.test_client()


def en_tant_que(client, utilisateur_id, role):
    with client.session_transaction() as session:
        session.update(utilisateur_id=utilisateur_id, nom="Test", role=role)


def test_boutique_publique(client):
    page = client.get("/producteurs/1").get_data(as_text=True)
    assert "Fatou Sarr" in page and "Récoltes en vente (1)" in page and "Mil souna" in page
    assert "Arachide" not in page and "Niébé" not in page
    assert "Créer un compte pour commander" in page
    assert client.get("/producteurs/2").status_code == 404  # pas un agriculteur


def test_boutique_vendeur_suspendu_introuvable(client):
    connexion = database.get_connexion()
    connexion.execute("UPDATE utilisateurs SET suspendu = 1 WHERE id = 1")
    connexion.commit()
    connexion.close()
    assert client.get("/producteurs/1").status_code == 404
    assert client.get("/producteurs/1/qr.svg").status_code == 404


def test_suivre_depuis_la_boutique(client):
    en_tant_que(client, 2, "client")
    reponse = client.post("/agriculteurs/1/suivre", data={"retour": "boutique"})
    assert reponse.headers["Location"].endswith("/producteurs/1")
    assert "✔️ Suivi" in client.get("/producteurs/1").get_data(as_text=True)


def test_qr_code_et_affiche(client):
    reponse = client.get("/producteurs/1/qr.svg")
    assert reponse.status_code == 200 and reponse.mimetype == "image/svg+xml"
    assert reponse.get_data(as_text=True).startswith("<svg") and 'xmlns="http://www.w3.org/2000/svg"' in reponse.get_data(as_text=True)

    assert "/connexion" in client.get("/espace-agriculteur/affiche").headers["Location"]
    en_tant_que(client, 1, "agriculteur")
    page = client.get("/espace-agriculteur/affiche").get_data(as_text=True)
    assert "Scannez pour commander" in page and "/producteurs/1/qr.svg" in page and "Mil souna" in page
    assert "Arachide" not in page
    assert "Mon affiche QR" in client.get("/producteurs/1").get_data(as_text=True)


def test_boutique_dans_le_plan_du_site(client):
    plan = client.get("/sitemap.xml").get_data(as_text=True)
    assert "/producteurs/1</loc>" in plan
    assert "Allow: /producteurs/" in client.get("/robots.txt").get_data(as_text=True)
