import pytest

import database
from app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    connexion = database.get_connexion()
    connexion.execute("INSERT INTO utilisateurs (nom, email, mot_de_passe, role) VALUES ('Moussa Diop', 'm@x.sn', 'x', 'agriculteur')")
    connexion.execute("INSERT INTO utilisateurs (nom, email, mot_de_passe, role) VALUES ('Awa', 'a@x.sn', 'x', 'client')")
    connexion.execute("""INSERT INTO recoltes (agriculteur_id, nom, quantite, prix, date_disponibilite, localite)
                         VALUES (1, 'Mil', '1 tonne', '300 FCFA / kg', '2026-01-01', 'Thiès')""")
    for statut, montant in (("en_attente", None), ("en_attente", None), ("confirmee", None), ("livree", 15000)):
        connexion.execute("""INSERT INTO commandes (recolte_id, client_id, quantite_demandee, statut, montant)
                             VALUES (1, 2, '10 kg', ?, ?)""", (statut, montant))
    connexion.commit()
    connexion.close()
    client = app.test_client()
    with client.session_transaction() as session:
        session.update(utilisateur_id=1, nom="Moussa Diop", role="agriculteur")
    return client


def test_activer_et_quitter_le_mode_simple(client):
    page = client.get("/espace-agriculteur").get_data(as_text=True)
    assert "Écran très simple" in page and "simple-grille" not in page

    client.post("/espace-agriculteur/mode-simple", data={"actif": "1"})
    page = client.get("/espace-agriculteur").get_data(as_text=True)
    assert "simple-grille" in page and "Bonjour" in page and "Moussa" in page
    assert '<span class="simple-pastille">2</span>' in page          # 2 commandes à confirmer
    assert "15 000 FCFA" in page and "1 annonce(s) en ligne" in page
    assert "data-lire=" in page and "speechSynthesis" in page
    # L'écran complet reste accessible
    assert "Mes récoltes publiées" in client.get("/espace-agriculteur?complet=1").get_data(as_text=True)

    client.post("/espace-agriculteur/mode-simple", data={"actif": "0"})
    assert "simple-grille" not in client.get("/espace-agriculteur").get_data(as_text=True)


def test_reserve_aux_agriculteurs(client):
    with client.session_transaction() as session:
        session.update(utilisateur_id=2, nom="Awa", role="client")
    assert "/connexion" in client.post("/espace-agriculteur/mode-simple", data={"actif": "1"}).headers["Location"]
