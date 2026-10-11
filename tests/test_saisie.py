import pytest

import database
from app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Base SQLite temporaire, pour ne pas toucher à app_agricole.db
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    # Ces tests portent sur la validation ; le jeton CSRF est testé dans test_csrf.py
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    return app.test_client()


def se_connecter(client, role, utilisateur_id=1):
    with client.session_transaction() as session:
        session["utilisateur_id"] = utilisateur_id
        session["nom"] = "Test"
        session["role"] = role


def test_nouvelle_recolte_garde_la_saisie_si_quantite_invalide(client):
    se_connecter(client, "agriculteur")
    reponse = client.post("/espace-agriculteur/nouvelle-recolte", data={
        "nom": "Mil de Thiès",
        "quantite": "beaucoup",
        "prix": "500 FCFA / kg",
        "date_disponibilite": "2026-11-01",
        "localite": "Thiès",
        "description": "Récolte de saison",
    })
    page = reponse.get_data(as_text=True)
    assert reponse.status_code == 200
    assert "nombre positif" in page
    assert 'value="Mil de Thiès"' in page
    assert 'value="beaucoup"' in page
    assert "Récolte de saison</textarea>" in page


def test_nouveau_produit_garde_le_type_choisi(client):
    se_connecter(client, "fournisseur")
    reponse = client.post("/espace-fournisseur/nouveau-produit", data={
        "nom": "Maïs hybride",
        "type_produit": "pepiniere",
        "quantite": "100 sachets",
        "prix": "gratuit",
        "localite": "Kaolack",
    })
    page = reponse.get_data(as_text=True)
    assert "montant positif" in page
    assert 'value="Maïs hybride"' in page
    assert 'value="pepiniere" selected' in page


def test_modifier_recolte_garde_la_saisie_et_la_fiche(client):
    connexion = database.get_connexion()
    connexion.execute(
        "INSERT INTO utilisateurs (nom, email, mot_de_passe, role) VALUES (?, ?, ?, ?)",
        ("Test", "test@exemple.sn", "x", "agriculteur"),
    )
    connexion.execute(
        """INSERT INTO recoltes (agriculteur_id, nom, quantite, prix, date_disponibilite, localite)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (1, "Arachide", "50 kg", "400 FCFA / kg", "2026-11-01", "Kaffrine"),
    )
    connexion.commit()
    connexion.close()

    se_connecter(client, "agriculteur")
    reponse = client.post("/espace-agriculteur/modifier-recolte/1", data={
        "nom": "Arachide décortiquée",
        "quantite": "50 kg",
        "prix": "gratuit",
        "date_disponibilite": "2026-11-01",
        "localite": "Kaffrine",
    })
    page = reponse.get_data(as_text=True)
    assert "montant positif" in page
    assert 'value="Arachide décortiquée"' in page
    assert 'value="gratuit"' in page
