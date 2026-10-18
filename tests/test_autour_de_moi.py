import pytest

import database
from app import app
from routes.client import rechercher_recoltes


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    connexion = database.get_connexion()
    # Agriculteurs : à Joal (Mbour, Thiès), à Thiès Est (Thiès, Thiès), à Kaolack, sans adresse
    for nom, commune, departement, region in (("Fatou", "Joal-Fadiouth", "Mbour", "Thiès"),
                                              ("Moussa", "Thiès Est", "Thiès", "Thiès"),
                                              ("Ibou", "Kaolack", "Kaolack", "Kaolack"),
                                              ("Ancien", None, None, None)):
        connexion.execute(
            """INSERT INTO utilisateurs (nom, email, mot_de_passe, role, pays, region, departement, commune)
               VALUES (?, ?, 'x', 'agriculteur', 'SN', ?, ?, ?)""",
            (nom, nom.lower() + "@x.sn", region, departement, commune))
    connexion.execute("""INSERT INTO utilisateurs (nom, email, mot_de_passe, role, pays, region, departement, commune)
                         VALUES ('Awa', 'a@x.sn', 'x', 'client', 'SN', 'Thiès', 'Mbour', 'Joal-Fadiouth')""")
    for agriculteur, nom, localite in ((3, "Arachide", "Kaolack"), (2, "Mil", "Thiès"),
                                       (1, "Oignons", "Joal"), (4, "Mangues", "Mbour (Saly)")):
        connexion.execute(
            """INSERT INTO recoltes (agriculteur_id, nom, quantite, prix, date_disponibilite, localite)
               VALUES (?, ?, '1 tonne', '300 FCFA / kg', '2026-01-01', ?)""", (agriculteur, nom, localite))
    connexion.commit()
    connexion.close()
    return app.test_client()


def test_tri_par_proximite(client):
    connexion = database.get_connexion()
    adresse = {"commune": "Joal-Fadiouth", "departement": "Mbour", "region": "Thiès"}
    recoltes = rechercher_recoltes(connexion, tri="proche", adresse=adresse)
    connexion.close()
    # Oignons : agriculteur de la même commune ; Mangues : localité dans le département (Mbour) ;
    # Mil : même région ; Arachide : ailleurs
    assert [(r["nom"], r["proximite"]) for r in recoltes] == [("Oignons", 3), ("Mangues", 2), ("Mil", 1),
                                                              ("Arachide", 0)]


def test_sans_adresse_rien_ne_change(client):
    connexion = database.get_connexion()
    recoltes = rechercher_recoltes(connexion)
    connexion.close()
    assert len(recoltes) == 4
    assert all(r["proximite"] == 0 for r in recoltes)


def test_catalogue_du_client_trie_pres_de_chez_lui(client):
    with client.session_transaction() as session:
        session.update(utilisateur_id=5, nom="Awa", role="client")
    page = client.get("/espace-client").get_data(as_text=True)
    assert "Récoltes près de chez toi d" in page and "Joal-Fadiouth" in page
    assert page.index("Oignons") < page.index("Mangues") < page.index("Mil") < page.index("Arachide")
    assert "Dans ta commune" in page and 'value="proche" selected' in page
    # Le tri choisi reste prioritaire
    page = client.get("/espace-client?tri=nom").get_data(as_text=True)
    assert page.index("Arachide") < page.index("Oignons")


def test_visiteur_sans_option_proche(client):
    page = client.get("/catalogue").get_data(as_text=True)
    assert 'value="proche"' not in page and "Dans ta commune" not in page
