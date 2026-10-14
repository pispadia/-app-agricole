import pytest

import database
from app import app
from core import lien_whatsapp, telephone_valide


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    return app.test_client()


def inscrire(client, **champs):
    donnees = {"nom": "Awa", "email": "awa@x.sn", "mot_de_passe": "mot-de-passe", "role": "client"}
    donnees.update(champs)
    return client.post("/inscription", data=donnees, follow_redirects=True).get_data(as_text=True)


def utilisateurs():
    connexion = database.get_connexion()
    lignes = connexion.execute("SELECT * FROM utilisateurs").fetchall()
    connexion.close()
    return lignes


def en_tant_que(client, utilisateur_id, role):
    with client.session_transaction() as session:
        session.update(utilisateur_id=utilisateur_id, nom="Test", role=role)


# --- Inscription plus solide

def test_mot_de_passe_trop_court_refuse(client):
    page = inscrire(client, mot_de_passe="court")
    assert "au moins 8 caractères" in page
    assert utilisateurs() == []
    assert 'value="Awa"' in page  # la saisie est conservée


def test_role_invalide_message_clair(client):
    page = inscrire(client, role="administrateur")
    assert "type de compte" in page
    assert "déjà utilisé" not in page
    assert utilisateurs() == []


def test_telephone_enregistre_et_valide(client):
    assert "nombre" not in inscrire(client, telephone="77 123 45 67")
    assert utilisateurs()[0]["telephone"] == "77 123 45 67"
    assert "entre 8 et 15 chiffres" in inscrire(client, email="b@x.sn", telephone="abc")
    assert len(utilisateurs()) == 1


def test_profil_telephone_et_mot_de_passe(client):
    inscrire(client)
    en_tant_que(client, 1, "client")
    client.post("/mon-profil", data={"nom": "Awa", "email": "awa@x.sn", "telephone": "+221 70 000 00 00",
                                     "nouveau_mot_de_passe": "", "mot_de_passe_actuel": "mot-de-passe"})
    assert utilisateurs()[0]["telephone"] == "+221 70 000 00 00"
    page = client.post("/mon-profil", data={"nom": "Awa", "email": "awa@x.sn", "telephone": "",
                                            "nouveau_mot_de_passe": "court", "mot_de_passe_actuel": "mot-de-passe"},
                       follow_redirects=True).get_data(as_text=True)
    assert "au moins 8 caractères" in page


# --- WhatsApp

def test_lien_whatsapp():
    assert lien_whatsapp("77 123 45 67") == "https://wa.me/221771234567"
    assert lien_whatsapp("+33 6 12 34 56 78") == "https://wa.me/33612345678"
    assert lien_whatsapp("00221 77 123 45 67") == "https://wa.me/221771234567"
    assert telephone_valide("") is None


def test_coordonnees_agriculteur_cachees_aux_clients(client):
    # Les clients ne doivent pas pouvoir contourner la plateforme (et la commission)
    inscrire(client, email="f@x.sn", role="agriculteur", telephone="77 123 45 67")
    inscrire(client, email="m@x.sn", nom="Moussa", role="agriculteur")  # sans téléphone
    connexion = database.get_connexion()
    for agriculteur_id, nom in ((1, "Mil"), (2, "Arachide")):
        connexion.execute(
            """INSERT INTO recoltes (agriculteur_id, nom, quantite, prix, date_disponibilite, localite)
               VALUES (?, ?, '100 kg', '500 FCFA / kg', '2026-11-01', 'Thiès')""", (agriculteur_id, nom))
    connexion.commit()
    connexion.close()
    en_tant_que(client, 3, "client")
    page = client.get("/espace-client").get_data(as_text=True)
    assert "wa.me" not in page and "77 123 45 67" not in page and "f@x.sn" not in page


# --- Notifications client

def test_client_notifie_quand_le_statut_change(client):
    inscrire(client, email="f@x.sn", role="agriculteur")
    inscrire(client, email="c@x.sn", role="client")
    connexion = database.get_connexion()
    connexion.execute(
        """INSERT INTO recoltes (agriculteur_id, nom, quantite, prix, date_disponibilite, localite)
           VALUES (1, 'Mil', '100 kg', '500 FCFA / kg', '2026-11-01', 'Thiès')""")
    connexion.commit()
    connexion.close()

    en_tant_que(client, 2, "client")
    client.post("/commander/1", data={"quantite_demandee": "20 kg"})
    assert "badge-epuise\" style=\"margin-left:2px;\">" not in client.get("/espace-client").get_data(as_text=True)

    en_tant_que(client, 1, "agriculteur")
    client.post("/espace-agriculteur/commandes/1/statut", data={"statut": "confirmee"})

    en_tant_que(client, 2, "client")
    page = client.get("/espace-client").get_data(as_text=True)
    assert "badge-epuise\" style=\"margin-left:2px;\">1<" in page  # badge 🔔 du menu
    page = client.get("/notifications").get_data(as_text=True)
    assert "Confirmée" in page and "Nouveau" in page
    # Une fois vue, la notification disparaît
    assert "badge-epuise\" style=\"margin-left:2px;\">" not in client.get("/espace-client").get_data(as_text=True)


def test_agriculteur_notifie_quand_le_client_annule(client):
    inscrire(client, email="f@x.sn", role="agriculteur")
    inscrire(client, email="c@x.sn", role="client")
    connexion = database.get_connexion()
    connexion.execute(
        """INSERT INTO recoltes (agriculteur_id, nom, quantite, prix, date_disponibilite, localite)
           VALUES (1, 'Mil', '100 kg', '500 FCFA / kg', '2026-11-01', 'Thiès')""")
    connexion.commit()
    connexion.close()
    en_tant_que(client, 2, "client")
    client.post("/commander/1", data={"quantite_demandee": "20 kg"})
    en_tant_que(client, 1, "agriculteur")
    client.get("/notifications")  # l'agriculteur a vu la commande
    en_tant_que(client, 2, "client")
    client.post("/mes-commandes/1/annuler")
    en_tant_que(client, 1, "agriculteur")
    assert "badge-epuise\" style=\"margin-left:2px;\">1<" in client.get("/espace-agriculteur").get_data(as_text=True)
