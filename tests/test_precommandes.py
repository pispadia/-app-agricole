from datetime import date, timedelta

import pytest

import database
import sms
from app import app

AUJOURDHUI = date.today()
DANS_UN_MOIS = (AUJOURDHUI + timedelta(days=30)).isoformat()
HIER = (AUJOURDHUI - timedelta(days=1)).isoformat()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    monkeypatch.setattr(sms, "alerter", lambda *args: None)
    connexion = database.get_connexion()
    for nom, email, role in (("Fatou", "f@x.sn", "agriculteur"), ("Awa", "a@x.sn", "client")):
        connexion.execute("INSERT INTO utilisateurs (nom, email, mot_de_passe, role) VALUES (?, ?, 'x', ?)", (nom, email, role))
    for nom, jour in (("Arachide", DANS_UN_MOIS), ("Mil", HIER)):
        connexion.execute(
            """INSERT INTO recoltes (agriculteur_id, nom, quantite, prix, date_disponibilite, localite)
               VALUES (1, ?, '100 kg', '500 FCFA / kg', ?, 'Thiès')""", (nom, jour))
    connexion.commit()
    connexion.close()
    return app.test_client()


def en_tant_que(client, utilisateur_id, role):
    with client.session_transaction() as session:
        session.update(utilisateur_id=utilisateur_id, nom="Test", role=role)


def test_catalogue_badge_et_filtre(client):
    en_tant_que(client, 2, "client")
    page = client.get("/espace-client").get_data(as_text=True)
    assert "🌱 À venir : prête le" in page and "Réserver (pré-commande)" in page and "Commander directement" in page
    a_venir = client.get("/espace-client?periode=a_venir").get_data(as_text=True)
    assert "Arachide" in a_venir and ">Mil<" not in a_venir
    maintenant = client.get("/espace-client?periode=maintenant").get_data(as_text=True)
    assert ">Mil<" in maintenant and "Arachide" not in maintenant


def test_reservation_visible_des_deux_cotes(client):
    en_tant_que(client, 2, "client")
    assert "Pré-commande : cette récolte sera prête" in client.get("/commander/1").get_data(as_text=True)
    client.post("/commander/1", data={"quantite_demandee": "20 kg"})
    assert "🌱 Pré-commande : récolte prévue le" in client.get("/mes-commandes").get_data(as_text=True)
    en_tant_que(client, 1, "agriculteur")
    assert "🌱 Pré-commande : récolte prévue le" in client.get("/espace-agriculteur/commandes").get_data(as_text=True)


@pytest.mark.parametrize("jour, accepte", [
    (DANS_UN_MOIS, True),
    ((AUJOURDHUI + timedelta(days=400)).isoformat(), False),  # plus d'un an à l'avance
    ("pas une date", False),
])
def test_date_de_disponibilite_verifiee(client, jour, accepte):
    en_tant_que(client, 1, "agriculteur")
    client.post("/espace-agriculteur/nouvelle-recolte", data={
        "nom": "Oignon", "quantite": "50 kg", "prix": "300 FCFA / kg", "date_disponibilite": jour, "localite": "Potou"})
    connexion = database.get_connexion()
    nombre = connexion.execute("SELECT COUNT(*) AS n FROM recoltes WHERE nom = 'Oignon'").fetchone()["n"]
    connexion.close()
    assert nombre == (1 if accepte else 0)
