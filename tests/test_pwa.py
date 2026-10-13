from app import app


def test_manifeste():
    reponse = app.test_client().get("/manifest.webmanifest")
    assert reponse.mimetype == "application/manifest+json"
    manifeste = reponse.get_json()
    assert manifeste["display"] == "standalone" and manifeste["start_url"] == "/"
    assert {icone["sizes"] for icone in manifeste["icons"]} == {"192x192", "512x512"}
    for icone in manifeste["icons"]:
        assert app.test_client().get(icone["src"]).status_code == 200


def test_service_worker_servi_a_la_racine():
    reponse = app.test_client().get("/sw.js")
    assert reponse.status_code == 200
    assert reponse.mimetype == "application/javascript"
    assert reponse.headers["Cache-Control"] == "no-cache"
    assert "/hors-ligne" in reponse.get_data(as_text=True)


def test_page_hors_ligne_et_liens_dans_les_pages():
    client = app.test_client()
    assert "Pas de connexion" in client.get("/hors-ligne").get_data(as_text=True)
    page = client.get("/").get_data(as_text=True)
    assert 'rel="manifest"' in page and "serviceWorker" in page
