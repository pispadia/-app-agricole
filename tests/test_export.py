import csv
import io
from datetime import date

import pytest

import core
import database
from app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    monkeypatch.setattr(core, "EMAILS_ADMIN", {"admin@x.sn"})
    annee = str(date.today().year)
    connexion = database.get_connexion()
    for nom, email, role in (("Fatou", "f@x.sn", "agriculteur"), ("Awa", "a@x.sn", "client"),
                             ("Admin", "admin@x.sn", "client")):
        connexion.execute("INSERT INTO utilisateurs (nom, email, mot_de_passe, role, email_confirme) "
                          "VALUES (?, ?, 'x', ?, ?)", (nom, email, role, email))
    connexion.execute(
        """INSERT INTO recoltes (agriculteur_id, nom, quantite, prix, date_disponibilite, localite)
           VALUES (1, '=HYPERLINK("http://pirate")', '10 kg', '500 FCFA / kg', '2026-11-01', 'Thiès')""")
    for statut, montant, commission, payee, jour in (("livree", 10000, 500, 1, f"{annee}-03-05 10:00:00"),
                                                      ("livree", 4000, 200, 0, f"{annee}-03-20 10:00:00"),
                                                      ("livree", 9999, 499, 1, "2000-01-01 10:00:00")):
        connexion.execute(
            """INSERT INTO commandes (recolte_id, client_id, quantite_demandee, statut, montant, commission,
                                      commission_payee, date_creation) VALUES (1, 2, '5 kg', ?, ?, ?, ?, ?)""",
            (statut, montant, commission, payee, jour))
    connexion.execute("INSERT INTO paiements_premium (utilisateur_id, reference, montant, statut, date_creation) "
                      "VALUES (1, 'W1', 3000, 'valide', ?)", (f"{annee}-03-10 10:00:00",))
    connexion.commit()
    connexion.close()
    client = app.test_client()
    with client.session_transaction() as session:
        session.update(utilisateur_id=3, nom="Admin", role="client")
    return client


def test_recapitulatif_par_mois(client):
    annee = date.today().year
    page = client.get("/admin/export").get_data(as_text=True)
    assert f"<td>{annee}-03</td><td>2</td><td>14000 F</td>" in page
    assert "<td>500 F</td><td>3000 F</td><td><strong>3500 F</strong></td>" in page  # commission réglée seulement


def test_export_ventes_csv(client):
    reponse = client.get("/admin/export/ventes.csv")
    assert reponse.mimetype == "text/csv" and "attachment" in reponse.headers["Content-Disposition"]
    texte = reponse.get_data(as_text=True)
    assert texte.startswith("﻿")
    lignes = list(csv.reader(io.StringIO(texte.lstrip("﻿")), delimiter=";"))
    assert lignes[0][0] == "N° commande" and len(lignes) == 3  # l'année 2000 est exclue
    assert lignes[1][3].startswith("'=")  # formule neutralisée
    assert lignes[1][8] == "10000" and lignes[1][11] == "oui"


def test_export_premium_et_acces(client):
    assert "W1;3000;valide" in client.get("/admin/export/premium.csv").get_data(as_text=True)
    with client.session_transaction() as session:
        session.update(utilisateur_id=2, nom="Awa", role="client")
    assert client.get("/admin/export/ventes.csv").status_code == 302
