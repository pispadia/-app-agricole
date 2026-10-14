"""Espace fournisseur de semences et catalogue des semences/pépinières."""
from datetime import date

from flask import render_template, request, redirect, url_for, session, flash
from database import get_connexion, COLONNES_PRODUIT
from core import app, encoder_photo, quantite_valide, prix_valide, utilisateur_connecte


@app.route("/espace-fournisseur")
def espace_fournisseur():
    if not utilisateur_connecte() or session["role"] != "fournisseur":
        return redirect(url_for("connexion"))

    connexion_bd = get_connexion()
    produits = connexion_bd.execute(
        f"SELECT {COLONNES_PRODUIT} FROM produits_fournisseur WHERE fournisseur_id = ? ORDER BY date_creation DESC",
        (session["utilisateur_id"],)
    ).fetchall()
    messages = connexion_bd.execute(
        """SELECT COUNT(*) AS total, SUM(CASE WHEN contacts_fournisseur.lu = 0 THEN 1 ELSE 0 END) AS non_lus
           FROM contacts_fournisseur
           JOIN produits_fournisseur ON contacts_fournisseur.produit_id = produits_fournisseur.id
           WHERE produits_fournisseur.fournisseur_id = ?""", (session["utilisateur_id"],)
    ).fetchone()
    connexion_bd.close()

    return render_template("espace_fournisseur.html", nom=session["nom"], produits=produits,
                           messages_total=messages["total"], messages_non_lus=messages["non_lus"] or 0)


@app.route("/espace-fournisseur/nouveau-produit", methods=["GET", "POST"])
def nouveau_produit():
    if not utilisateur_connecte() or session["role"] != "fournisseur":
        return redirect(url_for("connexion"))

    if request.method == "POST":
        nom = request.form["nom"]
        type_produit = request.form["type_produit"]
        variete = request.form.get("variete", "").strip() or None
        duree_croissance = request.form.get("duree_croissance", "").strip() or None
        try:
            quantite = quantite_valide(request.form["quantite"])
            prix = prix_valide(request.form["prix"])
        except ValueError as erreur:
            flash(str(erreur))
            return render_template("nouveau_produit.html", saisie=request.form)
        localite = request.form["localite"]
        description = request.form.get("description", "")

        fichier = request.files.get("photo")
        nom_photo = encoder_photo(fichier)

        connexion_bd = get_connexion()
        connexion_bd.execute(
            """INSERT INTO produits_fournisseur
               (fournisseur_id, nom, type_produit, variete, duree_croissance, quantite, prix, localite, description, photo)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (session["utilisateur_id"], nom, type_produit, variete, duree_croissance,
             quantite, prix, localite, description, nom_photo)
        )
        connexion_bd.commit()
        connexion_bd.close()

        flash("Produit publié avec succès.")
        return redirect(url_for("espace_fournisseur"))

    return render_template("nouveau_produit.html")


@app.route("/espace-fournisseur/modifier-produit/<int:produit_id>", methods=["GET", "POST"])
def modifier_produit(produit_id):
    if not utilisateur_connecte() or session["role"] != "fournisseur":
        return redirect(url_for("connexion"))

    connexion_bd = get_connexion()
    produit = connexion_bd.execute(
        "SELECT * FROM produits_fournisseur WHERE id = ? AND fournisseur_id = ?",
        (produit_id, session["utilisateur_id"])
    ).fetchone()

    if produit is None:
        connexion_bd.close()
        flash("Produit introuvable.")
        return redirect(url_for("espace_fournisseur"))

    if request.method == "POST":
        nom = request.form["nom"]
        type_produit = request.form["type_produit"]
        variete = request.form.get("variete", "").strip() or None
        duree_croissance = request.form.get("duree_croissance", "").strip() or None
        try:
            quantite = quantite_valide(request.form["quantite"])
            prix = prix_valide(request.form["prix"])
        except ValueError as erreur:
            flash(str(erreur))
            connexion_bd.close()
            return render_template("modifier_produit.html", produit={**dict(produit), **request.form.to_dict()})
        localite = request.form["localite"]
        description = request.form.get("description", "")
        statut = request.form.get("statut", "disponible")

        fichier = request.files.get("photo")
        nom_photo = encoder_photo(fichier) or produit["photo"]

        connexion_bd.execute(
            """UPDATE produits_fournisseur SET
               nom = ?, type_produit = ?, variete = ?, duree_croissance = ?, quantite = ?,
               prix = ?, localite = ?, description = ?, photo = ?, statut = ?
               WHERE id = ? AND fournisseur_id = ?""",
            (nom, type_produit, variete, duree_croissance, quantite, prix, localite,
             description, nom_photo, statut, produit_id, session["utilisateur_id"])
        )
        connexion_bd.commit()
        connexion_bd.close()

        flash("Produit mis à jour.")
        return redirect(url_for("espace_fournisseur"))

    connexion_bd.close()
    return render_template("modifier_produit.html", produit=produit)


@app.route("/espace-fournisseur/basculer-statut/<int:produit_id>", methods=["POST"])
def basculer_statut_produit(produit_id):
    if not utilisateur_connecte() or session["role"] != "fournisseur":
        return redirect(url_for("connexion"))

    connexion_bd = get_connexion()
    produit = connexion_bd.execute(
        "SELECT statut FROM produits_fournisseur WHERE id = ? AND fournisseur_id = ?",
        (produit_id, session["utilisateur_id"])
    ).fetchone()

    if produit:
        nouveau_statut = "epuise" if produit["statut"] == "disponible" else "disponible"
        connexion_bd.execute(
            "UPDATE produits_fournisseur SET statut = ? WHERE id = ? AND fournisseur_id = ?",
            (nouveau_statut, produit_id, session["utilisateur_id"])
        )
        connexion_bd.commit()

    connexion_bd.close()
    return redirect(url_for("espace_fournisseur"))


@app.route("/espace-fournisseur/messages")
def messages_recus():
    if not utilisateur_connecte() or session["role"] != "fournisseur":
        return redirect(url_for("connexion"))

    connexion_bd = get_connexion()
    messages = connexion_bd.execute(
        """SELECT contacts_fournisseur.*, produits_fournisseur.nom AS nom_produit,
                  utilisateurs.nom AS nom_agriculteur, utilisateurs.email AS email_agriculteur
           FROM contacts_fournisseur
           JOIN produits_fournisseur ON contacts_fournisseur.produit_id = produits_fournisseur.id
           JOIN utilisateurs ON contacts_fournisseur.agriculteur_id = utilisateurs.id
           WHERE produits_fournisseur.fournisseur_id = ?
           ORDER BY contacts_fournisseur.date_creation DESC""",
        (session["utilisateur_id"],)
    ).fetchall()
    connexion_bd.close()

    return render_template("messages_recus.html", nom=session["nom"], messages=messages)


@app.route("/semences-pepinieres")
def semences_pepinieres():
    if not utilisateur_connecte() or session["role"] != "agriculteur":
        return redirect(url_for("connexion"))

    recherche = request.args.get("recherche", "").strip()
    localite = request.args.get("localite", "").strip()
    type_produit = request.args.get("type_produit", "").strip()
    tri = request.args.get("tri", "recent")

    requete = """
        SELECT """ + COLONNES_PRODUIT + """, utilisateurs.nom AS nom_fournisseur,
               utilisateurs.telephone AS telephone_fournisseur,
               utilisateurs.premium_jusqu_au AS premium_fournisseur
        FROM produits_fournisseur
        JOIN utilisateurs ON produits_fournisseur.fournisseur_id = utilisateurs.id
        WHERE produits_fournisseur.statut = 'disponible'
    """
    parametres = []

    if recherche:
        requete += " AND (produits_fournisseur.nom LIKE ? OR produits_fournisseur.variete LIKE ? OR produits_fournisseur.description LIKE ?)"
        parametres.append(f"%{recherche}%")
        parametres.append(f"%{recherche}%")
        parametres.append(f"%{recherche}%")

    if localite:
        requete += " AND produits_fournisseur.localite LIKE ?"
        parametres.append(f"%{localite}%")

    if type_produit in ("semence", "pepiniere"):
        requete += " AND produits_fournisseur.type_produit = ?"
        parametres.append(type_produit)

    ordres = {
        "recent": "produits_fournisseur.date_creation DESC",
        "nom": "produits_fournisseur.nom ASC",
        "localite": "produits_fournisseur.localite ASC",
    }
    # Les annonces des membres Premium passent en premier
    aujourdhui = date.today().isoformat()
    requete += (" ORDER BY CASE WHEN utilisateurs.premium_jusqu_au >= ? THEN 0 ELSE 1 END, "
                + ordres.get(tri, ordres["recent"]))
    parametres.append(aujourdhui)

    connexion_bd = get_connexion()
    produits = connexion_bd.execute(requete, parametres).fetchall()
    localites = connexion_bd.execute(
        "SELECT DISTINCT localite FROM produits_fournisseur WHERE statut = 'disponible' ORDER BY localite"
    ).fetchall()
    connexion_bd.close()

    return render_template(
        "semences_pepinieres.html", nom=session["nom"], produits=produits,
        localites=localites, recherche=recherche, localite_choisie=localite, type_choisi=type_produit,
        tri_choisi=tri, aujourdhui=aujourdhui
    )


@app.route("/contacter-fournisseur/<int:produit_id>", methods=["GET", "POST"])
def contacter_fournisseur(produit_id):
    if not utilisateur_connecte() or session["role"] != "agriculteur":
        return redirect(url_for("connexion"))

    connexion_bd = get_connexion()
    produit = connexion_bd.execute(
        """SELECT produits_fournisseur.*, utilisateurs.nom AS nom_fournisseur
           FROM produits_fournisseur JOIN utilisateurs ON produits_fournisseur.fournisseur_id = utilisateurs.id
           WHERE produits_fournisseur.id = ?""", (produit_id,)
    ).fetchone()

    if produit is None:
        connexion_bd.close()
        flash("Produit introuvable.")
        return redirect(url_for("semences_pepinieres"))

    if request.method == "POST":
        message = request.form.get("message", "")

        connexion_bd.execute(
            "INSERT INTO contacts_fournisseur (produit_id, agriculteur_id, message) VALUES (?, ?, ?)",
            (produit_id, session["utilisateur_id"], message)
        )
        connexion_bd.commit()
        connexion_bd.close()

        flash(f"Ton message a été envoyé à {produit['nom_fournisseur']}.")
        return redirect(url_for("semences_pepinieres"))

    connexion_bd.close()
    return render_template("contacter_fournisseur.html", produit=produit)


# ---------- Espace Financeur ----------
