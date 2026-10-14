from datetime import date, timedelta

import pytest

import database
import promo
from app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    connexion = database.get_connexion()
    for nom, email, role in (("Fatou", "f@x.sn", "agriculteur"), ("Awa", "a@x.sn", "client"),
                             ("Moussa", "m@x.sn", "agriculteur")):
        connexion.execute("INSERT INTO utilisateurs (nom, email, mot_de_passe, role) VALUES (?, ?, 'x', ?)",
                          (nom, email, role))
    for nom in ("Oignons", "Mil"):
        connexion.execute(
            """INSERT INTO recoltes (agriculteur_id, nom, quantite, prix, date_disponibilite, localite)
               VALUES (1, ?, '1 tonne', '500 FCFA / kg', '2026-01-01', 'Potou')""", (nom,))
    connexion.commit()
    connexion.close()
    return app.test_client()


def en_tant_que(client, utilisateur_id, role):
    with client.session_transaction() as session:
        session.update(utilisateur_id=utilisateur_id, nom="Test", role=role)


def test_prix_reduit():
    assert promo.prix_reduit("500 FCFA / kg", 20) == "400 FCFA / kg"
    assert promo.prix_reduit("450 000 F / tonne", 10) == "405 000 F / tonne"
    assert promo.prix_reduit("1500 FCFA le sac", 15) == "1275 FCFA le sac"
    assert promo.prix_reduit("37 F / kg", 50) == "18 F / kg"
    assert promo.prix_reduit("prix à débattre", 20) == "prix à débattre"


def test_promo_active_selon_la_date():
    demain = (date.today() + timedelta(days=1)).isoformat()
    hier = (date.today() - timedelta(days=1)).isoformat()
    assert promo.promo_active({"promo_pourcent": 20, "promo_jusqu_au": demain}) == 20
    assert promo.promo_active({"promo_pourcent": 20, "promo_jusqu_au": hier}) == 0
    assert promo.promo_active({"promo_pourcent": None, "promo_jusqu_au": None}) == 0


def test_lancer_et_arreter_une_promo(client):
    en_tant_que(client, 1, "agriculteur")
    client.post("/espace-agriculteur/recolte/1/promo", data={"pourcent": "20", "duree": "7"})
    page = client.get("/espace-agriculteur").get_data(as_text=True)
    assert "400 FCFA / kg" in page and "−20 %" in page

    page = client.get("/annonce/1").get_data(as_text=True)
    assert "400 FCFA / kg" in page and "prix-barre" in page

    client.post("/espace-agriculteur/recolte/1/promo", data={"action": "arreter"})
    assert "400 FCFA / kg" not in client.get("/annonce/1").get_data(as_text=True)


def test_regles(client):
    en_tant_que(client, 1, "agriculteur")
    client.post("/espace-agriculteur/recolte/1/promo", data={"pourcent": "90", "duree": "7"})
    client.post("/espace-agriculteur/recolte/1/promo", data={"pourcent": "20", "duree": "100"})
    en_tant_que(client, 3, "agriculteur")  # pas son annonce
    client.post("/espace-agriculteur/recolte/1/promo", data={"pourcent": "20", "duree": "7"})
    en_tant_que(client, 2, "client")
    assert "/connexion" in client.post("/espace-agriculteur/recolte/1/promo",
                                       data={"pourcent": "20", "duree": "7"}).headers["Location"]
    connexion = database.get_connexion()
    assert connexion.execute("SELECT promo_pourcent FROM recoltes WHERE id = 1").fetchone()["promo_pourcent"] is None
    connexion.close()


def test_filtre_catalogue_et_prix_retenu_a_la_commande(client):
    en_tant_que(client, 1, "agriculteur")
    client.post("/espace-agriculteur/recolte/2/promo", data={"pourcent": "10", "duree": "3"})
    page = client.get("/catalogue?promo=1").get_data(as_text=True)
    assert "Mil" in page and "Oignons" not in page

    en_tant_que(client, 2, "client")
    client.post("/commander/2", data={"quantite_demandee": "20 kg", "mode_livraison": "retrait",
                                      "mode_paiement": "livraison"})
    connexion = database.get_connexion()
    assert connexion.execute("SELECT prix_promo FROM commandes").fetchone()["prix_promo"] == "450 FCFA / kg"
    connexion.close()
    en_tant_que(client, 1, "agriculteur")
    assert "Prix promo : 450 FCFA / kg" in client.get("/espace-agriculteur/commandes").get_data(as_text=True)
