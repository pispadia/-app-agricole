from datetime import date, timedelta

import pytest

import database
from app import app
from routes.statistiques import derniers_mois


def test_derniers_mois():
    assert derniers_mois(3, date(2026, 2, 10)) == ["2025-12", "2026-01", "2026-02"]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    connexion = database.get_connexion()
    for nom, email, role in (("Fatou", "f@x.sn", "agriculteur"), ("Awa", "a@x.sn", "client"),
                             ("Moussa", "m@x.sn", "agriculteur")):
        connexion.execute("INSERT INTO utilisateurs (nom, email, mot_de_passe, role) VALUES (?, ?, 'x', ?)",
                          (nom, email, role))
    for agriculteur_id, nom in ((1, "Mil"), (1, "Oignon"), (3, "Maïs")):
        connexion.execute(
            """INSERT INTO recoltes (agriculteur_id, nom, quantite, prix, date_disponibilite, localite)
               VALUES (?, ?, '100 kg', '500 FCFA / kg', '2026-11-01', 'Thiès')""", (agriculteur_id, nom))
    ce_mois = date.today().strftime("%Y-%m") + "-01 10:00:00"
    for recolte_id, statut, montant in ((1, "livree", 10000), (1, "livree", 5000), (2, "annulee", None),
                                        (1, "en_attente", None), (3, "livree", 99999)):
        connexion.execute(
            """INSERT INTO commandes (recolte_id, client_id, quantite_demandee, statut, montant, commission, date_creation)
               VALUES (?, 2, '5 kg', ?, ?, ?, ?)""",
            (recolte_id, statut, montant, montant and montant // 20, ce_mois))
    connexion.commit()
    connexion.close()
    client = app.test_client()
    with client.session_transaction() as session:
        session.update(utilisateur_id=1, nom="Fatou", role="agriculteur")
    return client


def rendre_premium():
    connexion = database.get_connexion()
    connexion.execute("UPDATE utilisateurs SET premium_jusqu_au = ? WHERE id = 1",
                      ((date.today() + timedelta(days=10)).isoformat(),))
    connexion.commit()
    connexion.close()


def test_chiffres_cles_pour_tous(client):
    page = client.get("/espace-agriculteur/statistiques").get_data(as_text=True)
    assert "15000 FCFA" in page                    # ses ventes livrées seulement (pas celles de Moussa)
    assert "Commandes reçues : <strong>4</strong>" in page
    assert "Taux d'acceptation : <strong>67 %</strong>" in page  # 2 livrées sur 3 traitées
    assert "Passer Premium" in page and "12 derniers mois" not in page


def test_detail_premium(client):
    rendre_premium()
    page = client.get("/espace-agriculteur/statistiques").get_data(as_text=True)
    assert "12 derniers mois" in page and "15000 F · 2" in page
    assert page.count('class="graphique-ligne"') == 12
    assert "<td>Mil</td><td>3</td><td>2</td><td>15000 FCFA</td>" in page
    assert "Maïs" not in page


def test_reserve_aux_agriculteurs(client):
    with client.session_transaction() as session:
        session.update(utilisateur_id=2, nom="Awa", role="client")
    assert client.get("/espace-agriculteur/statistiques").status_code == 302
