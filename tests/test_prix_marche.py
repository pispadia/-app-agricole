import pytest

import database
from app import app
from prix_marche import nom_affiche, prix_au_kg, produit_cle


def test_produit_cle_et_nom():
    assert produit_cle("Oignons violets de Galmi") == "oignon"
    assert produit_cle("Oignon") == "oignon"
    assert produit_cle("Maïs jaune") == "mais"
    assert produit_cle("Arachides décortiquées") == "arachide"
    assert nom_affiche("Maïs jaune") == "Maïs"


def test_prix_au_kg():
    assert prix_au_kg("500 FCFA / kg") == 500
    assert prix_au_kg("1 500 F/kilo") == 1500
    assert prix_au_kg("450 000 F / tonne") == 450
    assert prix_au_kg("2000") is None              # pas d'unité
    assert prix_au_kg("100 FCFA / sachet") is None  # pas un poids


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    connexion = database.get_connexion()
    connexion.execute("INSERT INTO utilisateurs (nom, email, mot_de_passe, role) VALUES ('F', 'f@x.sn', 'x', 'agriculteur')")
    for nom, prix in (("Mil de Thiès", "400 FCFA / kg"), ("Mil", "500 FCFA / kg"), ("Mil souna", "600 F/kg"),
                      ("Oignons", "300 FCFA / kg"),                    # une seule annonce : ignoré
                      ("Arachide", "2000"), ("Arachide", "sac de 50 kg à 20000 F")):  # sans prix au kilo
        connexion.execute(
            """INSERT INTO recoltes (agriculteur_id, nom, quantite, prix, date_disponibilite, localite)
               VALUES (1, ?, '100 kg', ?, '2026-11-01', 'Thiès')""", (nom, prix))
    connexion.commit()
    connexion.close()
    client = app.test_client()
    with client.session_transaction() as session:
        session.update(utilisateur_id=1, nom="F", role="client")
    return client


def test_page_prix_du_marche(client):
    page = client.get("/prix-du-marche").get_data(as_text=True)
    assert "Mil" in page and "500 FCFA/kg" in page and "400 – 600 FCFA/kg" in page
    assert "Oignon" not in page and "Arachide" not in page


def test_prix_courant_dans_le_catalogue(client):
    page = client.get("/espace-client").get_data(as_text=True)
    assert page.count("prix courant : 500 FCFA/kg") == 3
