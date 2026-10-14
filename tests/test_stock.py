import pytest

import database
import sms
from app import app
from stock import depasse_le_stock, lire_quantite, reste_apres


def test_lecture_et_decompte_des_quantites():
    assert lire_quantite("1,5 tonne") == (1500.0, "kg")
    assert lire_quantite("500 kg") == (500.0, "kg")
    assert lire_quantite("150 pièces") == (150.0, "piece")
    assert lire_quantite("3 sacs")[1] == lire_quantite("1 sac")[1] == "sac"
    assert reste_apres("500 kg", "50 kg") == (450.0, "450 kg")
    assert reste_apres("1 tonne", "50 kg") == (950.0, "0,95 tonne")
    assert reste_apres("150 pièces", "150 pièces") == (0, "0 pièces")
    assert reste_apres("200 kg", "3 sacs") is None  # unités différentes : on ne touche à rien
    assert depasse_le_stock("100 kg", "120 kg") and not depasse_le_stock("100 kg", "0,1 tonne")
    assert not depasse_le_stock("100 kg", "5 sacs")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    monkeypatch.setattr(sms, "alerter", lambda *args: None)
    connexion = database.get_connexion()
    connexion.execute("INSERT INTO utilisateurs (nom, email, mot_de_passe, role) VALUES ('Fatou', 'f@x.sn', 'x', 'agriculteur')")
    connexion.execute("INSERT INTO utilisateurs (nom, email, mot_de_passe, role) VALUES ('Awa', 'a@x.sn', 'x', 'client')")
    connexion.execute("""INSERT INTO recoltes (agriculteur_id, nom, quantite, prix, date_disponibilite, localite)
                         VALUES (1, 'Mil', '100 kg', '500 FCFA / kg', '2026-01-01', 'Thiès')""")
    connexion.execute("INSERT INTO commandes (recolte_id, client_id, quantite_demandee, statut) VALUES (1, 2, '60 kg', 'confirmee')")
    connexion.execute("INSERT INTO commandes (recolte_id, client_id, quantite_demandee, statut) VALUES (1, 2, '40 kg', 'confirmee')")
    connexion.commit()
    connexion.close()
    return app.test_client()


def recolte():
    connexion = database.get_connexion()
    ligne = connexion.execute("SELECT quantite, statut FROM recoltes WHERE id = 1").fetchone()
    connexion.close()
    return ligne["quantite"], ligne["statut"]


def connecter(client, utilisateur_id, role):
    with client.session_transaction() as session:
        session.update(utilisateur_id=utilisateur_id, nom="Test", role=role)


def test_livraisons_decomptent_le_stock_puis_epuisent(client):
    connecter(client, 1, "agriculteur")
    page = client.post("/espace-agriculteur/commandes/1/statut", data={"statut": "livree", "montant": "30000"},
                       follow_redirects=True).get_data(as_text=True)
    assert recolte() == ("40 kg", "disponible") and "il reste 40 kg" in page
    client.post("/espace-agriculteur/commandes/2/statut", data={"statut": "livree", "montant": "20000"})
    assert recolte() == ("0 kg", "epuise")


def test_commande_plus_grande_que_le_stock_refusee(client):
    connecter(client, 2, "client")
    page = client.post("/commander/1", data={"quantite_demandee": "150 kg", "mode_livraison": "retrait"},
                       follow_redirects=True).get_data(as_text=True)
    assert "Il ne reste que 100 kg" in page
    page = client.post("/panier/ajouter/1", data={"quantite": "2 tonnes"}, follow_redirects=True).get_data(as_text=True)
    assert "Il ne reste que 100 kg" in page
    connexion = database.get_connexion()
    assert connexion.execute("SELECT COUNT(*) AS n FROM commandes").fetchone()["n"] == 2
    connexion.close()
