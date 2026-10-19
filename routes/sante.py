"""Page de santé : répond tout de suite, sans base de données, pour les moniteurs qui gardent le serveur éveillé."""
from core import app


@app.route("/sante", methods=["GET", "HEAD"])
def sante():
    return "ok", 200, {"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store"}
