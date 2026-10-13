import pytest

import database
import sms
from app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    monkeypatch.setattr(sms, "alerter", lambda *args: None)

    connexion = database.get_connexion()
    for nom, email, role in (("Fatou", "f@x.sn", "agriculteur"), ("Awa", "a@x.sn", "client"),
                             ("Ibou", "i@x.sn", "client")):
        connexion.execute("INSERT INTO utilisateurs (nom, email, mot_de_passe, role) VALUES (?, ?, ?, ?)",
                          (nom, email, "x", role))
    connexion.execute(
        """INSERT INTO recoltes (agriculteur_id, nom, quantite, prix, date_disponibilite, localite)
           VALUES (1, 'Mil', '100 kg', '500 FCFA / kg', '2026-11-01', 'Thiès')""")
    # commande 1 (Awa) livrée, commande 2 (Awa) en attente, commande 3 (Ibou) livrée
    for client_id, statut in ((2, "livree"), (2, "en_attente"), (3, "livree")):
        connexion.execute(
            "INSERT INTO commandes (recolte_id, client_id, quantite_demandee, statut) VALUES (1, ?, '5 kg', ?)",
            (client_id, statut))
    connexion.commit()
    connexion.close()
    return app.test_client()


def en_tant_que(client, utilisateur_id, role):
    with client.session_transaction() as session:
        session.update(utilisateur_id=utilisateur_id, nom="Test", role=role)


def avis_enregistres():
    connexion = database.get_connexion()
    lignes = connexion.execute("SELECT commande_id, note, commentaire FROM avis ORDER BY id").fetchall()
    connexion.close()
    return [tuple(ligne) for ligne in lignes]


def test_avis_sur_commande_livree(client):
    en_tant_que(client, 2, "client")
    assert "Envoyer mon avis" in client.get("/mes-commandes").get_data(as_text=True)
    client.post("/mes-commandes/1/avis", data={"note": "4", "commentaire": " Très bon mil "})
    assert avis_enregistres() == [(1, 4, "Très bon mil")]
    page = client.get("/mes-commandes").get_data(as_text=True)
    assert "Ton avis" in page and "Envoyer mon avis" not in page


def test_un_seul_avis_par_commande(client):
    en_tant_que(client, 2, "client")
    client.post("/mes-commandes/1/avis", data={"note": "4"})
    client.post("/mes-commandes/1/avis", data={"note": "1"})
    assert avis_enregistres() == [(1, 4, None)]


@pytest.mark.parametrize("commande_id, note", [
    (2, "5"),   # pas encore livrée
    (3, "5"),   # commande d'un autre client
    (1, "0"), (1, "6"), (1, "beaucoup"),  # note invalide
])
def test_avis_refuses(client, commande_id, note):
    en_tant_que(client, 2, "client")
    client.post(f"/mes-commandes/{commande_id}/avis", data={"note": note})
    assert avis_enregistres() == []


def test_commentaire_trop_long(client):
    en_tant_que(client, 2, "client")
    client.post("/mes-commandes/1/avis", data={"note": "5", "commentaire": "x" * 501})
    assert avis_enregistres() == []


def test_seul_un_client_peut_donner_un_avis(client):
    en_tant_que(client, 1, "agriculteur")
    client.post("/mes-commandes/1/avis", data={"note": "5"})
    assert avis_enregistres() == []


def test_note_moyenne_dans_le_catalogue_et_la_page_avis(client):
    en_tant_que(client, 2, "client")
    client.post("/mes-commandes/1/avis", data={"note": "5", "commentaire": "Parfait"})
    en_tant_que(client, 3, "client")
    client.post("/mes-commandes/3/avis", data={"note": "4"})

    catalogue = client.get("/espace-client?tri=note").get_data(as_text=True)
    assert "4.5 (2 avis)" in catalogue
    page = client.get("/agriculteurs/1/avis").get_data(as_text=True)
    assert "4.5 (2 avis)" in page and "Parfait" in page and "★★★★★" in page


def test_page_avis_agriculteur_inconnu(client):
    en_tant_que(client, 2, "client")
    reponse = client.get("/agriculteurs/2/avis")  # Awa est cliente
    assert reponse.status_code == 302
