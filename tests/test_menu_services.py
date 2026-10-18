import pytest

import database
from app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    connexion = database.get_connexion()
    for nom, email, role in (("Fatou", "f@x.sn", "agriculteur"), ("Awa", "a@x.sn", "client")):
        connexion.execute("INSERT INTO utilisateurs (nom, email, mot_de_passe, role) VALUES (?, ?, 'x', ?)",
                          (nom, email, role))
    connexion.commit()
    connexion.close()
    return app.test_client()


def en_tant_que(client, utilisateur_id, role):
    with client.session_transaction() as session:
        session.update(utilisateur_id=utilisateur_id, nom="Test", role=role)


def test_menu_selon_le_compte(client):
    page = client.get("/").get_data(as_text=True)
    assert 'class="bouton-menu"' in page and "/inscription" in page and "Déconnexion" not in page

    en_tant_que(client, 1, "agriculteur")
    page = client.get("/espace-agriculteur").get_data(as_text=True)
    assert "/espace-agriculteur/nouvelle-recolte" in page and "/espace-agriculteur/rapport" in page
    assert "/mes-favoris" not in page

    en_tant_que(client, 2, "client")
    page = client.get("/espace-client").get_data(as_text=True)
    assert "/mes-favoris" in page and "/panier" in page and "/espace-agriculteur/rapport" not in page
