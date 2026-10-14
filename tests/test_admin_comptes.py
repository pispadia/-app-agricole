import pytest

import core
import database
from app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    monkeypatch.setattr(core, "EMAILS_ADMIN", {"admin@x.sn"})
    client = app.test_client()
    for nom, email, role in (("Admin", "admin@x.sn", "client"), ("Fatou", "f@x.sn", "agriculteur"),
                             ("Awa", "a@x.sn", "client")):
        client.post("/inscription", data={"nom": nom, "email": email, "mot_de_passe": "motdepasse", "role": role})
    connexion = database.get_connexion()
    connexion.execute("UPDATE utilisateurs SET email_confirme = email WHERE email = 'admin@x.sn'")
    connexion.commit()
    connexion.close()
    return client


def en_tant_que(client, utilisateur_id, role):
    with client.session_transaction() as session:
        session.update(utilisateur_id=utilisateur_id, nom="Test", role=role)


def suspendu(utilisateur_id):
    connexion = database.get_connexion()
    valeur = connexion.execute("SELECT suspendu FROM utilisateurs WHERE id = ?", (utilisateur_id,)).fetchone()[0]
    connexion.close()
    return valeur


def test_liste_recherche_et_chiffres(client):
    en_tant_que(client, 1, "client")
    assert "1 agriculteurs · 2 clients" in client.get("/admin").get_data(as_text=True)
    page = client.get("/admin/utilisateurs?recherche=fatou").get_data(as_text=True)
    assert "f@x.sn" in page and "a@x.sn" not in page
    page = client.get("/admin/utilisateurs?role=client").get_data(as_text=True)
    assert "a@x.sn" in page and "f@x.sn" not in page


def test_suspendre_bloque_la_connexion_et_la_session(client):
    # Fatou est connectée quand l'admin la suspend
    fatou = app.test_client()
    fatou.post("/connexion", data={"email": "f@x.sn", "mot_de_passe": "motdepasse"})
    assert fatou.get("/espace-agriculteur").status_code == 200

    en_tant_que(client, 1, "client")
    client.post("/admin/utilisateurs/2/suspendre")
    assert suspendu(2) == 1

    page = fatou.get("/espace-agriculteur", follow_redirects=True).get_data(as_text=True)
    assert "Ce compte est suspendu" in page
    page = fatou.post("/connexion", data={"email": "f@x.sn", "mot_de_passe": "motdepasse"},
                      follow_redirects=True).get_data(as_text=True)
    assert "Ce compte est suspendu" in page
    assert fatou.get("/espace-agriculteur").status_code == 302

    client.post("/admin/utilisateurs/2/reactiver")
    assert suspendu(2) == 0
    fatou.post("/connexion", data={"email": "f@x.sn", "mot_de_passe": "motdepasse"})
    assert fatou.get("/espace-agriculteur").status_code == 200


def test_admin_non_suspendable(client):
    en_tant_que(client, 1, "client")
    client.post("/admin/utilisateurs/1/suspendre")
    assert suspendu(1) == 0


def test_reserve_aux_admins(client):
    en_tant_que(client, 3, "client")
    assert client.get("/admin/utilisateurs").status_code == 302
    client.post("/admin/utilisateurs/2/suspendre")
    assert suspendu(2) == 0
