from datetime import date, timedelta

import pytest

import database
import push
import sms
from app import app
from routes.commandes_regulieres import passer_commandes_du_jour


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    monkeypatch.setattr(sms, "alerter", lambda *args: None)
    monkeypatch.setattr(push, "alerter", lambda *args: None)
    connexion = database.get_connexion()
    connexion.execute("INSERT INTO utilisateurs (nom, email, mot_de_passe, role) VALUES ('Fatou', 'f@x.sn', 'x', 'agriculteur')")
    connexion.execute("INSERT INTO utilisateurs (nom, email, mot_de_passe, role) VALUES ('Awa', 'a@x.sn', 'x', 'client')")
    connexion.execute("""INSERT INTO recoltes (agriculteur_id, nom, quantite, prix, date_disponibilite, localite)
                         VALUES (1, 'Oignon', '500 kg', '350 FCFA / kg', '2026-01-01', 'Potou')""")
    connexion.commit()
    connexion.close()
    client = app.test_client()
    with client.session_transaction() as session:
        session.update(utilisateur_id=2, nom="Awa", role="client")
    return client


def requete(sql, *params):
    connexion = database.get_connexion()
    lignes = connexion.execute(sql, params).fetchall()
    connexion.close()
    return lignes


def faire_passer(jours_plus_tard=0):
    """Avance l'échéance pour simuler le passage du temps, puis lance la tâche quotidienne."""
    connexion = database.get_connexion()
    connexion.execute("UPDATE commandes_regulieres SET prochaine_date = ?",
                      ((date.today() - timedelta(days=jours_plus_tard)).isoformat(),))
    connexion.commit()
    messages = passer_commandes_du_jour(connexion)
    connexion.close()
    return messages


def test_commande_reguliere_creee_puis_renouvelee(client):
    page = client.post("/commander/1", data={"quantite_demandee": "20 kg", "mode_livraison": "retrait",
                                             "repetition": "7"}, follow_redirects=True).get_data(as_text=True)
    assert "renouvelée chaque semaine" in page
    reguliere = requete("SELECT * FROM commandes_regulieres")[0]
    assert reguliere["prochaine_date"] == (date.today() + timedelta(days=7)).isoformat()
    assert len(requete("SELECT * FROM commandes")) == 1

    messages = faire_passer()
    commandes = requete("SELECT * FROM commandes ORDER BY id")
    assert len(commandes) == 2 and commandes[1]["reguliere_id"] == reguliere["id"]
    assert any("recommande 20 kg" in m[3] for m in messages)
    assert requete("SELECT prochaine_date FROM commandes_regulieres")[0]["prochaine_date"] == \
        (date.today() + timedelta(days=7)).isoformat()
    # Une seule commande par échéance, même si la tâche tourne deux fois
    connexion = database.get_connexion()
    passer_commandes_du_jour(connexion)
    connexion.close()
    assert len(requete("SELECT * FROM commandes")) == 2


def test_pause_arret_et_indisponibilite(client):
    client.post("/commander/1", data={"quantite_demandee": "20 kg", "mode_livraison": "retrait", "repetition": "14"})
    assert "Mes commandes régulières" in client.get("/mes-commandes").get_data(as_text=True)
    client.post("/commandes-regulieres/1/pause")
    faire_passer()
    assert len(requete("SELECT * FROM commandes")) == 1
    client.post("/commandes-regulieres/1/reprendre")
    connexion = database.get_connexion()
    connexion.execute("UPDATE recoltes SET statut = 'epuise'")
    connexion.commit()
    connexion.close()
    messages = faire_passer()
    assert len(requete("SELECT * FROM commandes")) == 1 and "non passée" in messages[0][2]
    with client.session_transaction() as session:
        session.update(utilisateur_id=1, role="agriculteur")
    assert client.post("/commandes-regulieres/1/arreter").status_code == 302
    assert len(requete("SELECT * FROM commandes_regulieres")) == 1  # un autre ne peut pas l'arrêter
    with client.session_transaction() as session:
        session.update(utilisateur_id=2, role="client")
    client.post("/commandes-regulieres/1/arreter")
    assert requete("SELECT * FROM commandes_regulieres") == []
