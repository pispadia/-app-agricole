import io

import pytest

import core
import database
import sms
from app import app

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    monkeypatch.setattr(core, "EMAILS_ADMIN", {"admin@x.sn"})
    connexion = database.get_connexion()
    connexion.execute("""INSERT INTO utilisateurs (nom, email, mot_de_passe, role, email_confirme)
                         VALUES ('Admin', 'admin@x.sn', 'x', 'client', 'admin@x.sn')""")
    connexion.execute("""INSERT INTO utilisateurs (nom, email, mot_de_passe, role, telephone)
                         VALUES ('Fatou', 'f@x.sn', 'x', 'agriculteur', '771234567')""")
    connexion.execute("""INSERT INTO recoltes (agriculteur_id, nom, quantite, prix, date_disponibilite, localite)
                         VALUES (2, 'Mil', '100 kg', '500 FCFA / kg', '2026-01-01', 'Thiès')""")
    connexion.commit()
    connexion.close()
    return app.test_client()


@pytest.fixture
def sms_envoyes(monkeypatch):
    envoyes = []
    monkeypatch.setattr(sms, "alerter", lambda telephone, message: envoyes.append((telephone, message)))
    return envoyes


def connecter(client, utilisateur_id, role):
    with client.session_transaction() as session:
        session.update(utilisateur_id=utilisateur_id, nom="Test", role=role)


def nb_pieces():
    connexion = database.get_connexion()
    n = connexion.execute("SELECT COUNT(*) AS n FROM verifications").fetchone()["n"]
    connexion.close()
    return n


def envoyer_piece(client):
    connecter(client, 2, "agriculteur")
    return client.post("/espace-agriculteur/verification", content_type="multipart/form-data",
                       data={"piece": (io.BytesIO(PNG), "cni.png")}, follow_redirects=True)


def test_parcours_de_verification(client, sms_envoyes):
    envoyer_piece(client)
    assert "en cours de vérification" in client.get("/espace-agriculteur/verification").get_data(as_text=True)
    assert nb_pieces() == 1
    # Pas de badge tant que l'admin n'a pas validé
    assert "✅ Vérifié" not in client.get("/annonce/1").get_data(as_text=True)

    connecter(client, 1, "client")
    page = client.get("/admin").get_data(as_text=True)
    assert "Pièces d'identité à contrôler" in page
    assert "Fatou" in client.get("/admin/verifications").get_data(as_text=True)
    reponse = client.get("/admin/verifications/2/piece")
    assert reponse.data == PNG and reponse.headers["Cache-Control"] == "no-store"

    client.post("/admin/verifications/2/valider")
    assert nb_pieces() == 0  # pièce effacée après la décision
    assert sms_envoyes and "vérifié" in sms_envoyes[0][1]
    assert client.get("/admin/verifications/2/piece").status_code == 404
    assert "✅ Vérifié" in client.get("/annonce/1").get_data(as_text=True)
    assert "✅ Vérifié" in client.get("/catalogue").get_data(as_text=True)


def test_refus_permet_de_renvoyer(client, sms_envoyes):
    envoyer_piece(client)
    connecter(client, 1, "client")
    client.post("/admin/verifications/2/refuser")
    assert nb_pieces() == 0
    page = envoyer_piece(client).get_data(as_text=True)
    assert "en cours de vérification" in page and nb_pieces() == 1


def test_piece_reservee_a_l_admin(client, sms_envoyes):
    envoyer_piece(client)
    reponse = client.get("/admin/verifications/2/piece")
    assert reponse.status_code == 302
    client.post("/admin/verifications/2/valider")
    connexion = database.get_connexion()
    statut = connexion.execute("SELECT verification FROM utilisateurs WHERE id = 2").fetchone()["verification"]
    connexion.close()
    assert statut == "en_attente"


def test_fichier_invalide_refuse(client):
    connecter(client, 2, "agriculteur")
    page = client.post("/espace-agriculteur/verification", content_type="multipart/form-data",
                       data={"piece": (io.BytesIO(b"pas une image"), "cni.png")}, follow_redirects=True)
    assert nb_pieces() == 0 and "photo lisible" in page.get_data(as_text=True)
