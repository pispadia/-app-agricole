import io
from types import SimpleNamespace

import anthropic
import pytest

import database
import ia
from app import app
from routes import assistant

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20


class FauxClient:
    def __init__(self, texte="Belles tomates fraîches.", stop_reason="end_turn", erreur=None):
        self.appels, self.texte, self.stop_reason, self.erreur = [], texte, stop_reason, erreur
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.appels.append(kwargs)
        if self.erreur:
            raise self.erreur
        return SimpleNamespace(stop_reason=self.stop_reason,
                               content=[SimpleNamespace(type="text", text=self.texte)])


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_NAME", str(tmp_path / "test.db"))
    database.init_db()
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "cle-de-test")
    monkeypatch.delenv("IA_MODELE", raising=False)
    connexion = database.get_connexion()
    connexion.execute("INSERT INTO utilisateurs (nom, email, mot_de_passe, role) VALUES ('Fatou', 'f@x.sn', 'x', 'agriculteur')")
    connexion.commit()
    connexion.close()
    client = app.test_client()
    with client.session_transaction() as session:
        session.update(utilisateur_id=1, nom="Fatou", role="agriculteur")
    return client


def test_redaction_d_annonce(client, monkeypatch):
    faux = FauxClient()
    monkeypatch.setattr(ia, "_client", lambda: faux)
    assert "Écrire la description avec l" in client.get("/espace-agriculteur/nouvelle-recolte").get_data(as_text=True)
    reponse = client.post("/ia/annonce", json={"nom": "Tomates", "quantite": "200 kg", "localite": "Niayes",
                                               "description": "bien rouges"})
    assert reponse.get_json() == {"texte": "Belles tomates fraîches."}
    appel = faux.appels[0]
    assert appel["model"] == "claude-opus-5-5" and appel["output_config"] == {"effort": "low"}
    assert appel["fallbacks"] == "default" and appel["betas"] == ["server-side-fallback-2026-07-01"]
    assert "Tomates" in appel["messages"][0]["content"] and "bien rouges" in appel["messages"][0]["content"]
    assert client.post("/ia/annonce", json={"nom": ""}).status_code == 400


def test_conseiller_avec_photo_et_modele_au_choix(client, monkeypatch):
    faux = FauxClient(texte="Probablement le mildiou.")
    monkeypatch.setattr(ia, "_client", lambda: faux)
    monkeypatch.setenv("IA_MODELE", "claude-haiku-5-5")
    assert "Conseiller agricole" in client.get("/espace-agriculteur").get_data(as_text=True)
    page = client.post("/espace-agriculteur/conseiller", content_type="multipart/form-data",
                       data={"question": "Taches noires sur mes tomates", "photo": (io.BytesIO(PNG), "p.png")}
                       ).get_data(as_text=True)
    assert "Probablement le mildiou." in page
    contenu = faux.appels[0]["messages"][0]["content"]
    assert contenu[0]["type"] == "image" and contenu[0]["source"]["media_type"] == "image/png"
    assert faux.appels[0]["model"] == "claude-haiku-5-5"


def test_refus_erreurs_et_quota(client, monkeypatch):
    monkeypatch.setattr(ia, "_client", lambda: FauxClient(stop_reason="refusal", texte=""))
    assert "ne peut pas répondre" in client.post("/ia/annonce", json={"nom": "Mil"}).get_json()["erreur"]
    requete = SimpleNamespace(method="POST", url="https://api.anthropic.com")
    monkeypatch.setattr(ia, "_client", lambda: FauxClient(erreur=anthropic.APITimeoutError(request=requete)))
    assert "trop de temps" in client.post("/ia/annonce", json={"nom": "Mil"}).get_json()["erreur"]
    monkeypatch.setattr(ia, "_client", lambda: FauxClient())
    monkeypatch.setattr(assistant, "QUOTA_JOUR", 3)
    codes = [client.post("/ia/annonce", json={"nom": "Mil"}).status_code for _ in range(2)]
    assert codes == [200, 429]  # 2 demandes déjà faites ci-dessus


def test_desactive_sans_cle_et_reserve_aux_agriculteurs(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert "Écrire la description avec l" not in client.get("/espace-agriculteur/nouvelle-recolte").get_data(as_text=True)
    assert "pas encore activé" in client.post("/ia/annonce", json={"nom": "Mil"}).get_json()["erreur"]
    with client.session_transaction() as session:
        session.update(role="client")
    assert client.post("/ia/annonce", json={"nom": "Mil"}).status_code == 401
