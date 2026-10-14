from datetime import date

import pytest

import database
from app import app
from routes import rapport_mensuel


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
    connexion.execute(
        """INSERT INTO recoltes (agriculteur_id, nom, quantite, prix, date_disponibilite, localite, date_creation)
           VALUES (1, 'Oignons', '1 tonne', '500 FCFA / kg', '2026-09-01', 'Potou', '2026-09-02 10:00:00')""")
    for statut, montant, jour in (("livree", 20000, "2026-09-05"), ("livree", 5000, "2026-09-20"),
                                  ("annulee", None, "2026-09-21"), ("livree", 9999, "2026-08-30")):
        connexion.execute(
            """INSERT INTO commandes (recolte_id, client_id, quantite_demandee, statut, montant, date_creation)
               VALUES (1, 2, '10 kg', ?, ?, ?)""", (statut, montant, jour + " 09:00:00"))
    connexion.execute("""INSERT INTO avis (commande_id, client_id, agriculteur_id, note, date_creation)
                         VALUES (1, 2, 1, 4, '2026-09-06 10:00:00')""")
    connexion.execute("""INSERT INTO agriculteurs_suivis (client_id, agriculteur_id, date_creation)
                         VALUES (2, 1, '2026-09-07 10:00:00')""")
    connexion.commit()
    connexion.close()
    return app.test_client()


def test_mois_precedent():
    assert rapport_mensuel.mois_precedent(date(2026, 10, 14)) == "2026-09"
    assert rapport_mensuel.mois_precedent(date(2026, 1, 1)) == "2025-12"
    assert rapport_mensuel.libelle_mois("2026-09") == "septembre 2026"


def test_chiffres_du_mois(client):
    connexion = database.get_connexion()
    chiffres = rapport_mensuel.rapport(connexion, 1, "2026-09")
    connexion.close()
    assert (chiffres["recues"], chiffres["livrees"], chiffres["ventes"]) == (3, 2, 25000)
    assert chiffres["produits"] == [("Oignons", 3)]
    assert (chiffres["nb_avis"], chiffres["note_avis"], chiffres["abonnes"], chiffres["publiees"]) == (1, 4.0, 1, 1)


def test_rapports_envoyes_une_fois_et_seulement_si_activite(client):
    connexion = database.get_connexion()
    with app.test_request_context():
        envois = rapport_mensuel.preparer_rapports(connexion, date(2026, 10, 1))
        assert [(e[0], e[1]) for e in envois] == [("f@x.sn", "Ton bilan de septembre 2026 sur App Agricole")]
        assert "25 000 FCFA" in envois[0][2] and "Oignons (3)" in envois[0][2]
        # Moussa (sans activité) est marqué sans e-mail ; personne ne le reçoit deux fois
        assert rapport_mensuel.preparer_rapports(connexion, date(2026, 10, 2)) == []
        # Le mois suivant, on recommence
        connexion.execute("UPDATE utilisateurs SET rapport_mensuel = 0 WHERE id = 1")
        connexion.commit()
        assert rapport_mensuel.preparer_rapports(connexion, date(2026, 11, 1)) == []
    connexion.close()


def test_page_du_bilan_et_desactivation(client):
    with client.session_transaction() as session:
        session.update(utilisateur_id=1, nom="Fatou", role="agriculteur")
    page = client.get("/espace-agriculteur/rapport?mois=2026-09").get_data(as_text=True)
    assert "septembre 2026" in page and "25 000" in page
    assert client.get("/espace-agriculteur/rapport?mois=n%27importe").status_code == 200
    client.post("/espace-agriculteur/rapport", data={})
    connexion = database.get_connexion()
    assert connexion.execute("SELECT rapport_mensuel FROM utilisateurs WHERE id = 1").fetchone()["rapport_mensuel"] == 0
    connexion.close()
    with client.session_transaction() as session:
        session.update(utilisateur_id=2, nom="Awa", role="client")
    assert "/connexion" in client.get("/espace-agriculteur/rapport").headers["Location"]
