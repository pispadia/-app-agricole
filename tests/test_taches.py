from datetime import date, datetime, timedelta

import pytest

import database
import sms
from app import app
from routes import taches


class ThreadImmediat:
    def __init__(self, target, daemon=None):
        self.target = target

    def start(self):
        self.target()


@pytest.fixture
def envois(monkeypatch):
    liste = []
    monkeypatch.setattr(taches.threading, "Thread", ThreadImmediat)
    monkeypatch.setattr(taches, "envoyer_email", lambda dest, sujet, html: liste.append((dest, sujet)))
    monkeypatch.setattr(sms, "alerter", lambda *args: None)
    return liste


@pytest.fixture
def client(tmp_path, monkeypatch, envois):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    monkeypatch.setenv("TACHES_TOKEN", "secret")
    aujourdhui = date.today()
    il_y_a_3_jours = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    connexion = database.get_connexion()
    connexion.execute("INSERT INTO utilisateurs (nom, email, mot_de_passe, role) VALUES ('Fatou', 'f@x.sn', 'x', 'agriculteur')")
    connexion.execute("INSERT INTO utilisateurs (nom, email, mot_de_passe, role, premium_jusqu_au) VALUES ('Awa', 'a@x.sn', 'x', 'client', ?)",
                      ((aujourdhui + timedelta(days=3)).isoformat(),))
    # Récolte 1 prête aujourd'hui (réservée il y a 3 jours) ; récolte 2 prête dans 10 jours
    for jour in (aujourdhui.isoformat(), (aujourdhui + timedelta(days=10)).isoformat()):
        connexion.execute(
            """INSERT INTO recoltes (agriculteur_id, nom, quantite, prix, date_disponibilite, localite)
               VALUES (1, 'Arachide', '100 kg', '500 FCFA / kg', ?, 'Thiès')""", (jour,))
    for recolte_id, statut, quand in ((1, "confirmee", il_y_a_3_jours),   # pré-commande prête
                                      (2, "en_attente", il_y_a_3_jours),  # en attente depuis 3 jours
                                      (2, "en_attente", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))):
        connexion.execute("INSERT INTO commandes (recolte_id, client_id, quantite_demandee, statut, date_creation) "
                          "VALUES (?, 2, '5 kg', ?, ?)", (recolte_id, statut, quand))
    connexion.commit()
    connexion.close()
    return app.test_client()


def appeler(client, jeton="secret"):
    return client.post("/taches/quotidiennes", headers={"Authorization": f"Bearer {jeton}"})


def test_rappels_envoyes_une_seule_fois(client, envois):
    reponse = appeler(client)
    assert reponse.get_json()["rappels"] == 3
    sujets = sorted(sujet for _, sujet in envois)
    assert sujets == ["Ta réservation de Arachide est prête", "Ton abonnement Premium se termine bientôt",
                      "Une commande de Arachide attend ta réponse"]
    assert sorted(dest for dest, _ in envois) == ["a@x.sn", "a@x.sn", "f@x.sn"]
    envois.clear()
    assert appeler(client).get_json()["rappels"] == 0
    assert envois == []


def test_jeton_obligatoire(client, monkeypatch):
    assert appeler(client, "mauvais").status_code == 404
    assert client.post("/taches/quotidiennes").status_code == 404
    monkeypatch.delenv("TACHES_TOKEN")
    assert appeler(client, "").status_code == 404
