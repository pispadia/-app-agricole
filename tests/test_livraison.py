import pytest

import database
import sms
from app import app


@pytest.fixture
def envoyes(monkeypatch):
    liste = []
    monkeypatch.setattr(sms, "alerter", lambda telephone, message: liste.append((telephone, message)))
    return liste


@pytest.fixture
def client(tmp_path, monkeypatch, envoyes):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)

    connexion = database.get_connexion()
    for nom, email, role in (("Fatou", "f@x.sn", "agriculteur"), ("Awa", "a@x.sn", "client")):
        connexion.execute(
            "INSERT INTO utilisateurs (nom, email, mot_de_passe, role, telephone) VALUES (?, ?, ?, ?, '77 000 00 00')",
            (nom, email, "x", role))
    for nom in ("Mil", "Niébé"):
        connexion.execute(
            """INSERT INTO recoltes (agriculteur_id, nom, quantite, prix, date_disponibilite, localite)
               VALUES (1, ?, '100 kg', '500 FCFA / kg', '2026-11-01', 'Thiès')""", (nom,))
    connexion.commit()
    connexion.close()
    return app.test_client()


def en_tant_que(client, utilisateur_id, role):
    with client.session_transaction() as session:
        session.update(utilisateur_id=utilisateur_id, nom="Test", role=role)


def commandes():
    connexion = database.get_connexion()
    lignes = connexion.execute(
        """SELECT statut, mode_livraison, adresse_livraison, date_livraison_prevue, frais_livraison
           FROM commandes ORDER BY id""").fetchall()
    connexion.close()
    return [tuple(ligne) for ligne in lignes]


def test_commande_avec_retrait_par_defaut(client):
    en_tant_que(client, 2, "client")
    client.post("/commander/1", data={"quantite_demandee": "20 kg"})
    assert commandes() == [("en_attente", "retrait", None, None, None)]


def test_commande_avec_livraison(client):
    en_tant_que(client, 2, "client")
    client.post("/commander/1", data={"quantite_demandee": "20 kg", "mode_livraison": "livraison",
                                      "adresse_livraison": "  Médina,\n rue 6 x 11 "})
    assert commandes() == [("en_attente", "livraison", "Médina, rue 6 x 11", None, None)]
    page = client.get("/mes-commandes").get_data(as_text=True)
    assert "Livraison à domicile" in page and "Médina, rue 6 x 11" in page


@pytest.mark.parametrize("donnees", [
    {"mode_livraison": "livraison", "adresse_livraison": "  "},
    {"mode_livraison": "livraison", "adresse_livraison": "x" * 301},
    {"mode_livraison": "drone"},
])
def test_livraison_invalide_refusee(client, donnees):
    en_tant_que(client, 2, "client")
    page = client.post("/commander/1", data={"quantite_demandee": "20 kg", **donnees},
                       follow_redirects=True).get_data(as_text=True)
    assert commandes() == []
    assert "quantite_demandee" in page  # le formulaire de commande est réaffiché


def test_panier_avec_livraison(client):
    en_tant_que(client, 2, "client")
    with client.session_transaction() as session:
        session["panier"] = [{"recolte_id": 1, "quantite": "5 kg"}, {"recolte_id": 2, "quantite": "3 kg"}]
    client.post("/panier/valider", data={"mode_livraison": "livraison"})  # adresse manquante
    assert commandes() == []
    client.post("/panier/valider", data={"mode_livraison": "livraison", "adresse_livraison": "Thiès, Grand Standing"})
    assert [c[1:3] for c in commandes()] == [("livraison", "Thiès, Grand Standing")] * 2


def commande_livraison(client):
    en_tant_que(client, 2, "client")
    client.post("/commander/1", data={"quantite_demandee": "20 kg", "mode_livraison": "livraison",
                                      "adresse_livraison": "Médina"})
    en_tant_que(client, 1, "agriculteur")


def test_confirmation_avec_date_et_frais(client, envoyes):
    commande_livraison(client)
    page = client.get("/espace-agriculteur/commandes").get_data(as_text=True)
    assert "Médina" in page and 'name="frais_livraison"' in page
    client.post("/espace-agriculteur/commandes/1/statut",
                data={"statut": "confirmee", "date_livraison_prevue": "2026-11-05", "frais_livraison": "1 500 FCFA"})
    assert commandes() == [("confirmee", "livraison", "Médina", "2026-11-05", 1500)]
    assert "Livraison prévu(e) le 05/11/2026. Frais de livraison : 1500 FCFA." in envoyes[-1][1]

    en_tant_que(client, 2, "client")
    page = client.get("/mes-commandes").get_data(as_text=True)
    assert "Prévue le 05/11/2026" in page and "1500 FCFA" in page


def test_confirmation_sans_planning(client, envoyes):
    commande_livraison(client)
    client.post("/espace-agriculteur/commandes/1/statut", data={"statut": "confirmee"})
    assert commandes() == [("confirmee", "livraison", "Médina", None, None)]
    assert envoyes[-1][1].endswith("par Test.")


@pytest.mark.parametrize("donnees", [{"date_livraison_prevue": "05/11/2026"}, {"frais_livraison": "gratuit"}])
def test_planning_invalide_refuse(client, donnees):
    commande_livraison(client)
    client.post("/espace-agriculteur/commandes/1/statut", data={"statut": "confirmee", **donnees})
    assert commandes()[0][0] == "en_attente"
