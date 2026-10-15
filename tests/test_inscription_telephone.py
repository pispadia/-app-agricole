import pytest

import database
import sms
from app import app
from geographie import lieu_valide, telephone_international, texte_lieu

LIEU = {"pays": "SN", "region": "Thiès", "departement": "Mbour", "commune": "Joal-Fadiouth"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    return app.test_client()


@pytest.fixture
def sms_envoyes(monkeypatch):
    envoyes = []
    monkeypatch.setattr(sms, "sms_actif", lambda: True)
    monkeypatch.setattr(sms, "envoyer_sms", lambda tel, msg: envoyes.append((tel, msg)) or True)
    return envoyes


def utilisateur(champ, valeur):
    connexion = database.get_connexion()
    ligne = connexion.execute(f"SELECT * FROM utilisateurs WHERE {champ} = ?", (valeur,)).fetchone()
    connexion.close()
    return ligne


def inscrire_par_telephone(client, telephone="77 123 45 67", **champs):
    donnees = {**LIEU, "nom": "Moussa Diop", "mode": "telephone", "telephone": telephone,
               "mot_de_passe": "motdepasse", "role": "agriculteur"}
    donnees.update(champs)
    return client.post("/inscription", data=donnees, follow_redirects=True).get_data(as_text=True)


def test_telephone_international():
    assert telephone_international("77 123 45 67") == "+221771234567"
    assert telephone_international("+221 77 123 45 67") == "+221771234567"
    assert telephone_international("00221771234567") == "+221771234567"
    assert telephone_international("70 12 34 56", "ML") == "+22370123456"
    assert telephone_international("06 12 34 56 78", "FR") == "+33612345678"
    with pytest.raises(ValueError):
        telephone_international("123")


def test_lieu_avec_autre():
    lieu = lieu_valide({"pays": "SN", "region": "Thiès", "departement": "Mbour", "commune": "__autre__",
                        "commune_autre": " Keur  Mbaye ", "localite": "Escale"})
    assert lieu == {"pays": "SN", "region": "Thiès", "departement": "Mbour", "commune": "Keur Mbaye",
                    "localite": "Escale"}
    # Hors Sénégal, le département est facultatif
    assert lieu_valide({"pays": "ML", "region": "__autre__", "region_autre": "Ségou", "departement": "__autre__",
                        "commune": "__autre__", "commune_autre": "Niono"})["departement"] is None
    for manque in ({"pays": "XX"}, {"pays": "SN", "region": "Thiès"},
                   {"pays": "SN", "region": "Thiès", "departement": "Mbour", "commune": "__autre__"}):
        with pytest.raises(ValueError):
            lieu_valide(manque)
    assert texte_lieu({"commune": "Joal-Fadiouth", "localite": "Ngazobil", "region": "Thiès", "pays": "SN"}) \
        == "Ngazobil, Joal-Fadiouth, Thiès"


def test_inscription_et_connexion_par_telephone(client):
    page = inscrire_par_telephone(client, localite="Ngazobil")
    assert "connecte-toi avec ton numéro" in page
    u = utilisateur("telephone_connexion", "+221771234567")
    assert u["email"] is None and u["telephone"] == "+221771234567"
    assert (u["pays"], u["region"], u["departement"], u["commune"], u["localite"]) == \
        ("SN", "Thiès", "Mbour", "Joal-Fadiouth", "Ngazobil")

    # Connexion avec le numéro écrit autrement
    reponse = client.post("/connexion", data={"identifiant": "+221 77 123 45 67", "mot_de_passe": "motdepasse"})
    assert reponse.headers["Location"].endswith("/espace-agriculteur")
    client.get("/deconnexion")
    reponse = client.post("/connexion", data={"identifiant": "771234567", "mot_de_passe": "mauvais"},
                          follow_redirects=True)
    assert "incorrect" in reponse.get_data(as_text=True)


def test_un_seul_compte_par_numero(client):
    inscrire_par_telephone(client)
    page = inscrire_par_telephone(client, telephone="+221771234567", nom="Autre")
    assert "déjà utilisé" in page
    connexion = database.get_connexion()
    assert connexion.execute("SELECT COUNT(*) AS n FROM utilisateurs").fetchone()["n"] == 1
    connexion.close()


def test_inscription_email_toujours_possible(client):
    page = client.post("/inscription", data={**LIEU, "nom": "Awa", "mode": "email", "email": "awa@x.sn",
                                             "mot_de_passe": "motdepasse", "role": "client"},
                       follow_redirects=True).get_data(as_text=True)
    assert "Compte créé" in page
    assert utilisateur("email", "awa@x.sn")["telephone_connexion"] is None
    page = client.post("/inscription", data={**LIEU, "nom": "X", "mode": "email", "email": "pas-un-email",
                                             "mot_de_passe": "motdepasse", "role": "client"},
                       follow_redirects=True).get_data(as_text=True)
    assert "Adresse e-mail invalide" in page


def test_adresse_obligatoire(client):
    page = inscrire_par_telephone(client, region="", region_autre="")
    assert "Indique ta région" in page
    assert utilisateur("telephone_connexion", "+221771234567") is None


def test_formulaire_propose_les_listes(client):
    page = client.get("/inscription").get_data(as_text=True)
    assert 'name="mode" value="telephone" checked' in page
    assert '"Mbour"' in page and "Joal-Fadiouth" in page and 'name="commune_autre"' in page


def test_mot_de_passe_oublie_par_sms(client, sms_envoyes):
    inscrire_par_telephone(client)
    reponse = client.post("/mot-de-passe-oublie", data={"identifiant": "77 123 45 67"})
    assert reponse.headers["Location"].endswith("/reinitialiser-par-sms")
    (telephone, message), = sms_envoyes
    code = message.split("ton code est ")[1][:6]
    assert telephone == "+221771234567" and code.isdigit()

    client.post("/reinitialiser-par-sms", data={"code": "000000" if code != "000000" else "111111",
                                                "mot_de_passe": "nouveau-mdp", "confirmation": "nouveau-mdp"})
    assert client.post("/connexion", data={"identifiant": "771234567", "mot_de_passe": "nouveau-mdp"}
                       ).headers["Location"].endswith("/connexion")
    client.post("/reinitialiser-par-sms", data={"code": code, "mot_de_passe": "nouveau-mdp",
                                                "confirmation": "nouveau-mdp"})
    assert client.post("/connexion", data={"identifiant": "771234567", "mot_de_passe": "nouveau-mdp"}
                       ).headers["Location"].endswith("/espace-agriculteur")
    # Le code ne sert qu'une fois
    connexion = database.get_connexion()
    assert connexion.execute("SELECT COUNT(*) AS n FROM codes_sms").fetchone()["n"] == 0
    connexion.close()


def test_numero_inconnu_meme_reponse_sans_sms(client, sms_envoyes):
    reponse = client.post("/mot-de-passe-oublie", data={"identifiant": "76 000 00 00"})
    assert reponse.headers["Location"].endswith("/reinitialiser-par-sms")
    assert sms_envoyes == []


def test_code_bloque_apres_trop_d_essais(client, sms_envoyes):
    inscrire_par_telephone(client)
    client.post("/mot-de-passe-oublie", data={"identifiant": "771234567"})
    code = sms_envoyes[0][1].split("ton code est ")[1][:6]
    faux = "000000" if code != "000000" else "111111"
    for _ in range(5):
        client.post("/reinitialiser-par-sms", data={"code": faux, "mot_de_passe": "nouveau-mdp",
                                                    "confirmation": "nouveau-mdp"})
    client.post("/reinitialiser-par-sms", data={"code": code, "mot_de_passe": "nouveau-mdp",
                                                "confirmation": "nouveau-mdp"})
    assert client.post("/connexion", data={"identifiant": "771234567", "mot_de_passe": "motdepasse"}
                       ).headers["Location"].endswith("/espace-agriculteur")


def test_profil_compte_telephone(client):
    inscrire_par_telephone(client)
    client.post("/connexion", data={"identifiant": "771234567", "mot_de_passe": "motdepasse"})
    page = client.get("/mon-profil").get_data(as_text=True)
    assert "Compte lié à ton numéro +221771234567" in page
    client.post("/mon-profil", data={**LIEU, "commune": "Mbour", "nom": "Moussa", "telephone": "78 000 00 00",
                                     "email": "", "mot_de_passe_actuel": "motdepasse"})
    u = utilisateur("telephone_connexion", "+221780000000")
    assert u["commune"] == "Mbour" and u["email"] is None


def test_contact_sans_email(client):
    inscrire_par_telephone(client)
    client.post("/connexion", data={"identifiant": "771234567", "mot_de_passe": "motdepasse"})
    page = client.post("/contact", data={"categorie": "compte", "message": "Bonjour"},
                       follow_redirects=True).get_data(as_text=True)
    assert "Message envoyé" in page
