import pytest

import core
import database
from app import app
from routes import moderation


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    monkeypatch.setattr(core, "EMAILS_ADMIN", {"admin@x.sn"})
    connexion = database.get_connexion()
    connexion.execute("INSERT INTO utilisateurs (nom, email, mot_de_passe, role) VALUES ('Fatou', 'f@x.sn', 'x', 'agriculteur')")
    for i in range(4):
        connexion.execute("INSERT INTO utilisateurs (nom, email, mot_de_passe, role) VALUES (?, ?, 'x', 'client')",
                          (f"Client {i}", f"c{i}@x.sn"))
    connexion.execute("INSERT INTO utilisateurs (nom, email, mot_de_passe, role, email_confirme) "
                      "VALUES ('Admin', 'admin@x.sn', 'x', 'client', 'admin@x.sn')")
    connexion.execute(
        """INSERT INTO recoltes (agriculteur_id, nom, quantite, prix, date_disponibilite, localite)
           VALUES (1, 'Mil', '100 kg', '500 FCFA / kg', '2026-01-01', 'Thiès')""")
    connexion.commit()
    connexion.close()
    return app.test_client()


def en_tant_que(client, utilisateur_id, role="client"):
    with client.session_transaction() as session:
        session.update(utilisateur_id=utilisateur_id, nom="Test", role=role)


def masquee():
    connexion = database.get_connexion()
    valeur = connexion.execute("SELECT masquee FROM recoltes WHERE id = 1").fetchone()["masquee"]
    connexion.close()
    return valeur


def signaler(client, utilisateur_id, motif="arnaque"):
    en_tant_que(client, utilisateur_id)
    client.post("/annonce/1/signaler", data={"motif": motif, "commentaire": "Il demande d'appeler le 771234567"})


def test_masquage_automatique_au_troisieme_signalement(client):
    assert "Signaler cette annonce" in client.get("/annonce/1").get_data(as_text=True)
    signaler(client, 2)
    signaler(client, 2)  # même personne : compté une fois
    signaler(client, 3)
    assert masquee() == 0
    signaler(client, 4)
    assert masquee() == 1
    assert client.get("/annonce/1").status_code == 404
    assert "Mil" not in client.get("/catalogue").get_data(as_text=True)
    en_tant_que(client, 5)
    assert client.post("/commander/1", data={"quantite_demandee": "5 kg"}).status_code == 302
    connexion = database.get_connexion()
    assert connexion.execute("SELECT COUNT(*) AS n FROM commandes").fetchone()["n"] == 0
    connexion.close()


def test_admin_retablit_ou_masque(client):
    signaler(client, 2)
    en_tant_que(client, 6)
    page = client.get("/admin/signalements").get_data(as_text=True)
    assert "Arnaque ou vendeur suspect" in page and "[numéro masqué]" in page
    client.post("/admin/signalements/1/masquer")
    assert masquee() == 1
    assert "Aucun signalement en attente" in client.get("/admin/signalements").get_data(as_text=True)
    client.post("/admin/signalements/1/retablir")
    assert masquee() == 0


def test_signalement_refuse(client):
    en_tant_que(client, 1, "agriculteur")  # sa propre annonce
    client.post("/annonce/1/signaler", data={"motif": "arnaque"})
    en_tant_que(client, 2)
    client.post("/annonce/1/signaler", data={"motif": "pas un motif"})
    connexion = database.get_connexion()
    assert connexion.execute("SELECT COUNT(*) AS n FROM signalements").fetchone()["n"] == 0
    connexion.close()
    assert app.test_client().get("/annonce/1/signaler").headers["Location"].startswith("/connexion")


def test_reserve_aux_admins(client):
    en_tant_que(client, 2)
    assert client.get("/admin/signalements").status_code == 302
    client.post("/admin/signalements/1/masquer")
    assert masquee() == 0
    assert moderation.SEUIL_MASQUAGE == 3
