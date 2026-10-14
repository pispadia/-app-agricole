import io
import json
import zipfile

import pytest

import core
import database
from app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    monkeypatch.setattr(core, "EMAILS_ADMIN", {"admin@x.sn"})
    connexion = database.get_connexion()
    connexion.execute("""INSERT INTO utilisateurs (nom, email, mot_de_passe, role, email_confirme)
                         VALUES ('Admin', 'admin@x.sn', 'x', 'client', 'admin@x.sn')""")
    connexion.execute("INSERT INTO utilisateurs (nom, email, mot_de_passe, role) VALUES ('Fatou', 'f@x.sn', 'x', 'agriculteur')")
    for i in range(120):  # plus que la taille d'un paquet
        connexion.execute("""INSERT INTO recoltes (agriculteur_id, nom, quantite, prix, date_disponibilite, localite, photo)
                             VALUES (2, ?, '1 kg', '5 FCFA', '2026-01-01', 'Thiès', 'data:image/png;base64,AAAA')""", (f"R{i}",))
    connexion.execute("INSERT INTO verifications (utilisateur_id, piece) VALUES (2, 'data:image/png;base64,SECRET')")
    connexion.execute("INSERT INTO parametres (cle, valeur) VALUES ('test', 'x')")
    connexion.commit()
    connexion.close()
    return app.test_client()


def connecter(client, utilisateur_id):
    with client.session_transaction() as session:
        session.update(utilisateur_id=utilisateur_id, nom="Test", role="client")


def lire(reponse):
    archive = zipfile.ZipFile(io.BytesIO(reponse.data))
    return {nom: [json.loads(l) for l in archive.read(nom).decode().splitlines()]
            for nom in archive.namelist() if nom.endswith(".jsonl")}, archive.read("LISEZMOI.txt").decode()


def test_sauvegarde_complete_sans_photos_par_defaut(client):
    connecter(client, 1)
    assert "Sauvegardes" in client.get("/admin").get_data(as_text=True)
    reponse = client.post("/admin/sauvegarde/telecharger")
    assert reponse.mimetype == "application/zip"
    tables, lisezmoi = lire(reponse)
    assert set(tables) == {f"{t}.jsonl" for t in database.TABLES}
    assert len(tables["recoltes.jsonl"]) == 120 and "photo" not in tables["recoltes.jsonl"][0]
    assert tables["parametres.jsonl"] == [{"cle": "test", "valeur": "x"}]
    assert "piece" not in tables["verifications.jsonl"][0]  # jamais exportée
    assert "recoltes : 120 ligne(s)" in lisezmoi


def test_avec_photos_et_reservee_a_l_admin(client):
    connecter(client, 1)
    tables, _ = lire(client.post("/admin/sauvegarde/telecharger", data={"photos": "1"}))
    assert tables["recoltes.jsonl"][0]["photo"].startswith("data:image/png")
    connecter(client, 2)
    assert client.post("/admin/sauvegarde/telecharger").status_code == 302
