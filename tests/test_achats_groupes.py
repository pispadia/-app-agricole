from datetime import date, timedelta

import pytest

import database
import push
from app import app
from routes import achats_groupes


@pytest.fixture
def alertes(monkeypatch):
    liste = []
    monkeypatch.setattr(push, "alerter", lambda uid, tel, msg, url="/": liste.append((uid, msg)))
    return liste


@pytest.fixture
def client(tmp_path, monkeypatch, alertes):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    connexion = database.get_connexion()
    for nom, email, role in (("Fatou", "f@x.sn", "agriculteur"), ("Awa Diop", "a@x.sn", "client"),
                             ("Ibou", "i@x.sn", "client"), ("Moussa", "m@x.sn", "client")):
        connexion.execute("INSERT INTO utilisateurs (nom, email, mot_de_passe, role) VALUES (?, ?, 'x', ?)",
                          (nom, email, role))
    connexion.execute(
        """INSERT INTO recoltes (agriculteur_id, nom, quantite, prix, prix_gros, quantite_gros_min,
                                 date_disponibilite, localite)
           VALUES (1, 'Oignons', '2 tonnes', '350 FCFA / kg', '280 FCFA / kg', 'à partir de 1 tonne',
                   '2026-01-01', 'Potou')""")
    connexion.execute(  # sans prix de gros : pas d'achat groupé
        """INSERT INTO recoltes (agriculteur_id, nom, quantite, prix, date_disponibilite, localite)
           VALUES (1, 'Mil', '500 kg', '300 FCFA / kg', '2026-01-01', 'Thiès')""")
    connexion.commit()
    connexion.close()
    return app.test_client()


def en_tant_que(client, utilisateur_id, role="client"):
    with client.session_transaction() as session:
        session.update(utilisateur_id=utilisateur_id, nom="Test", role=role)


def commandes():
    connexion = database.get_connexion()
    lignes = connexion.execute(
        "SELECT client_id, quantite_demandee, prix_propose, negociation, achat_groupe_id FROM commandes ORDER BY client_id"
    ).fetchall()
    connexion.close()
    return [tuple(l) for l in lignes]


def test_seuil_gros():
    assert achats_groupes.seuil_gros("à partir de 1 tonne") == "1 tonne"
    assert achats_groupes.seuil_gros("500 kg") == "500 kg"
    assert achats_groupes.seuil_gros("en gros") is None


def test_groupe_jusqu_a_l_objectif(client, alertes):
    en_tant_que(client, 2)
    assert "Lancer l'achat groupé" in client.get("/annonce/1").get_data(as_text=True)
    reponse = client.post("/annonce/1/achat-groupe", data={"quantite": "400 kg"})
    assert reponse.headers["Location"].endswith("/achats-groupes/1")
    page = client.get("/achats-groupes/1").get_data(as_text=True)
    assert "il manque <strong>0,6 tonne</strong>" in page and "Ta part : 400 kg" in page

    en_tant_que(client, 3)
    client.post("/annonce/1/achat-groupe", data={"quantite": "300 kg"})  # rejoint le groupe ouvert
    assert commandes() == []
    page = client.get("/annonce/1").get_data(as_text=True)
    assert "2 participant(s)" in page and "il manque 0,3 tonne" in page

    en_tant_que(client, 4)
    client.post("/achats-groupes/1", data={"quantite": "0,3 tonne"})
    assert commandes() == [(2, "400 kg", "280 FCFA / kg", "acceptee", 1), (3, "300 kg", "280 FCFA / kg", "acceptee", 1),
                           (4, "0,3 tonne", "280 FCFA / kg", "acceptee", 1)]
    assert len(alertes) == 4 and alertes[-1][0] == 1  # 3 clients + l'agriculteur
    assert "Objectif atteint" in client.get("/achats-groupes/1").get_data(as_text=True)
    # Groupe terminé : on ne peut plus le rejoindre, un nouveau peut être lancé
    en_tant_que(client, 2)
    client.post("/achats-groupes/1", data={"quantite": "100 kg"})
    assert len(commandes()) == 3


def test_regles(client):
    en_tant_que(client, 2)
    client.post("/annonce/2/achat-groupe", data={"quantite": "100 kg"})       # pas de prix de gros
    client.post("/annonce/1/achat-groupe", data={"quantite": "10 sacs"})      # autre unité
    client.post("/annonce/1/achat-groupe", data={"quantite": "3 tonnes"})     # plus que le stock
    connexion = database.get_connexion()
    assert connexion.execute("SELECT COUNT(*) AS n FROM achats_groupes").fetchone()["n"] == 0
    connexion.close()
    en_tant_que(client, 1, "agriculteur")
    assert "/connexion" in client.post("/annonce/1/achat-groupe", data={"quantite": "100 kg"}).headers["Location"]


def test_modifier_quitter_et_expirer(client):
    en_tant_que(client, 2)
    client.post("/annonce/1/achat-groupe", data={"quantite": "400 kg"})
    client.post("/achats-groupes/1", data={"quantite": "500 kg"})
    en_tant_que(client, 3)
    client.post("/achats-groupes/1", data={"quantite": "100 kg"})
    client.post("/achats-groupes/1", data={"action": "quitter"})
    assert "0,5 tonne</strong> sur 1 tonne" in client.get("/achats-groupes/1").get_data(as_text=True)
    en_tant_que(client, 2)
    assert "Mes achats groupés en cours" in client.get("/mes-commandes").get_data(as_text=True)

    connexion = database.get_connexion()
    connexion.execute("UPDATE achats_groupes SET date_limite = ?", ((date.today() - timedelta(days=1)).isoformat(),))
    connexion.commit()
    messages = achats_groupes.expirer_groupes(connexion)
    assert [m[0] for m in messages] == ["a@x.sn"]
    assert connexion.execute("SELECT statut FROM achats_groupes").fetchone()["statut"] == "expire"
    connexion.close()
    assert commandes() == []
