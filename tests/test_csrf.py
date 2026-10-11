import re

import pytest

import database
from app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    return app.test_client()


def compter_utilisateurs():
    connexion = database.get_connexion()
    total = connexion.execute("SELECT COUNT(*) AS n FROM utilisateurs").fetchone()["n"]
    connexion.close()
    return total


INSCRIPTION = {"nom": "Awa", "email": "awa@exemple.sn", "mot_de_passe": "secret", "role": "client"}


def test_formulaire_sans_jeton_refuse(client):
    reponse = client.post("/inscription", data=INSCRIPTION, headers={"Referer": "https://site-malveillant.example/"})
    assert compter_utilisateurs() == 0
    # Pas de redirection vers un site extérieur
    assert reponse.status_code == 302
    assert "site-malveillant" not in reponse.headers["Location"]


def test_formulaire_avec_jeton_accepte(client):
    page = client.get("/inscription").get_data(as_text=True)
    jeton = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    client.post("/inscription", data={**INSCRIPTION, "csrf_token": jeton})
    assert compter_utilisateurs() == 1


def test_tous_les_formulaires_post_ont_un_jeton():
    import glob
    for chemin in glob.glob("templates/*.html"):
        contenu = open(chemin, encoding="utf-8").read()
        formulaires = re.findall(r'<form\b[^>]*method="POST"[^>]*>', contenu, re.I)
        jetons = contenu.count('name="csrf_token"')
        assert jetons == len(formulaires), chemin
