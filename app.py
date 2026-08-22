import os
import base64
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from database import get_connexion, init_db

app = Flask(__name__)
app.secret_key = "change-cette-cle-plus-tard"  # nécessaire pour utiliser les sessions

EXTENSIONS_AUTORISEES = {"png", "jpg", "jpeg", "webp"}
TAILLE_MAX_PHOTO = 2 * 1024 * 1024  # 2 Mo, pour garder la base de données légère

init_db()


def extension_autorisee(nom_fichier):
    return "." in nom_fichier and nom_fichier.rsplit(".", 1)[1].lower() in EXTENSIONS_AUTORISEES


def encoder_photo(fichier):
    """
    Encode une photo envoyée en formulaire directement en base64 pour la stocker
    dans la base de données (au lieu du disque, qui n'est pas permanent en ligne).
    Retourne une chaîne "data:image/...;base64,...." prête à être utilisée dans un
    attribut src d'image, ou None si aucune photo valide n'a été envoyée.
    """
    if not fichier or not fichier.filename or not extension_autorisee(fichier.filename):
        return None

    contenu = fichier.read()
    if len(contenu) > TAILLE_MAX_PHOTO:
        flash("La photo est trop volumineuse (2 Mo maximum) et n'a pas été enregistrée.")
        return None

    extension = fichier.filename.rsplit(".", 1)[1].lower()
    type_mime = "image/jpeg" if extension in ("jpg", "jpeg") else f"image/{extension}"
    photo_base64 = base64.b64encode(contenu).decode("utf-8")
    return f"data:{type_mime};base64,{photo_base64}"


@app.route("/")
def accueil():
    return render_template("accueil.html")


@app.route("/inscription", methods=["GET", "POST"])
def inscription():
    if request.method == "POST":
        nom = request.form["nom"]
        email = request.form["email"]
        mot_de_passe = request.form["mot_de_passe"]
        role = request.form["role"]

        mot_de_passe_hache = generate_password_hash(mot_de_passe)

        connexion = get_connexion()
        try:
            connexion.execute(
                "INSERT INTO utilisateurs (nom, email, mot_de_passe, role) VALUES (?, ?, ?, ?)",
                (nom, email, mot_de_passe_hache, role)
            )
            connexion.commit()
        except Exception:
            flash("Cet email est déjà utilisé.")
            return redirect(url_for("inscription"))
        finally:
            connexion.close()

        flash("Compte créé avec succès, tu peux te connecter.")
        return redirect(url_for("connexion"))

    return render_template("inscription.html")


@app.route("/connexion", methods=["GET", "POST"])
def connexion():
    if request.method == "POST":
        email = request.form["email"]
        mot_de_passe = request.form["mot_de_passe"]

        connexion_bd = get_connexion()
        utilisateur = connexion_bd.execute(
            "SELECT * FROM utilisateurs WHERE email = ?", (email,)
        ).fetchone()
        connexion_bd.close()

        if utilisateur and check_password_hash(utilisateur["mot_de_passe"], mot_de_passe):
            session["utilisateur_id"] = utilisateur["id"]
            session["nom"] = utilisateur["nom"]
            session["role"] = utilisateur["role"]

            if utilisateur["role"] == "client":
                return redirect(url_for("espace_client"))
            elif utilisateur["role"] == "agriculteur":
                return redirect(url_for("espace_agriculteur"))
            elif utilisateur["role"] == "fournisseur":
                return redirect(url_for("espace_fournisseur"))
            elif utilisateur["role"] == "financeur":
                return redirect(url_for("espace_financeur"))
        else:
            flash("Email ou mot de passe incorrect.")
            return redirect(url_for("connexion"))

    return render_template("connexion.html")


@app.route("/deconnexion")
def deconnexion():
    session.clear()
    return redirect(url_for("accueil"))


def utilisateur_connecte():
    return "utilisateur_id" in session


@app.route("/espace-client")
def espace_client():
    if not utilisateur_connecte() or session["role"] != "client":
        return redirect(url_for("connexion"))

    recherche = request.args.get("recherche", "").strip()
    localite = request.args.get("localite", "").strip()

    requete = """
        SELECT recoltes.*, utilisateurs.nom AS nom_agriculteur
        FROM recoltes
        JOIN utilisateurs ON recoltes.agriculteur_id = utilisateurs.id
        WHERE recoltes.statut = 'disponible'
    """
    parametres = []

    if recherche:
        requete += " AND recoltes.nom LIKE ?"
        parametres.append(f"%{recherche}%")

    if localite:
        requete += " AND recoltes.localite LIKE ?"
        parametres.append(f"%{localite}%")

    requete += " ORDER BY recoltes.date_creation DESC"

    connexion_bd = get_connexion()
    recoltes = connexion_bd.execute(requete, parametres).fetchall()
    localites = connexion_bd.execute(
        "SELECT DISTINCT localite FROM recoltes WHERE statut = 'disponible' ORDER BY localite"
    ).fetchall()
    connexion_bd.close()

    return render_template(
        "espace_client.html", nom=session["nom"], recoltes=recoltes,
        localites=localites, recherche=recherche, localite_choisie=localite,
        taille_panier=len(session.get("panier", []))
    )


def get_recolte_avec_agriculteur(connexion_bd, recolte_id):
    return connexion_bd.execute(
        """SELECT recoltes.*, utilisateurs.nom AS nom_agriculteur
           FROM recoltes JOIN utilisateurs ON recoltes.agriculteur_id = utilisateurs.id
           WHERE recoltes.id = ?""", (recolte_id,)
    ).fetchone()


@app.route("/panier/ajouter/<int:recolte_id>", methods=["POST"])
def ajouter_au_panier(recolte_id):
    if not utilisateur_connecte() or session["role"] != "client":
        return redirect(url_for("connexion"))

    quantite = request.form.get("quantite", "").strip()
    if not quantite:
        flash("Indique une quantité avant d'ajouter au panier.")
        return redirect(url_for("espace_client"))

    panier = session.get("panier", [])
    panier.append({"recolte_id": recolte_id, "quantite": quantite})
    session["panier"] = panier

    flash("Ajouté au panier.")
    return redirect(url_for("espace_client"))


@app.route("/panier")
def voir_panier():
    if not utilisateur_connecte() or session["role"] != "client":
        return redirect(url_for("connexion"))

    connexion_bd = get_connexion()
    articles = []
    for index, item in enumerate(session.get("panier", [])):
        recolte = get_recolte_avec_agriculteur(connexion_bd, item["recolte_id"])
        if recolte:
            articles.append({"index": index, "recolte": recolte, "quantite": item["quantite"]})
    connexion_bd.close()

    return render_template("panier.html", nom=session["nom"], articles=articles)


@app.route("/panier/supprimer/<int:index>", methods=["POST"])
def supprimer_du_panier(index):
    if not utilisateur_connecte() or session["role"] != "client":
        return redirect(url_for("connexion"))

    panier = session.get("panier", [])
    if 0 <= index < len(panier):
        panier.pop(index)
        session["panier"] = panier

    return redirect(url_for("voir_panier"))


@app.route("/panier/valider", methods=["POST"])
def valider_panier():
    if not utilisateur_connecte() or session["role"] != "client":
        return redirect(url_for("connexion"))

    panier = session.get("panier", [])
    if not panier:
        flash("Ton panier est vide.")
        return redirect(url_for("espace_client"))

    connexion_bd = get_connexion()
    for item in panier:
        connexion_bd.execute(
            "INSERT INTO commandes (recolte_id, client_id, quantite_demandee, message) VALUES (?, ?, ?, ?)",
            (item["recolte_id"], session["utilisateur_id"], item["quantite"], "Commande depuis le panier")
        )
    connexion_bd.commit()
    connexion_bd.close()

    session["panier"] = []
    flash("Tes commandes ont été envoyées aux agriculteurs concernés.")
    return redirect(url_for("espace_client"))


@app.route("/commander/<int:recolte_id>", methods=["GET", "POST"])
def commander(recolte_id):
    if not utilisateur_connecte() or session["role"] != "client":
        return redirect(url_for("connexion"))

    connexion_bd = get_connexion()
    recolte = connexion_bd.execute(
        """SELECT recoltes.*, utilisateurs.nom AS nom_agriculteur
           FROM recoltes JOIN utilisateurs ON recoltes.agriculteur_id = utilisateurs.id
           WHERE recoltes.id = ?""", (recolte_id,)
    ).fetchone()

    if recolte is None:
        connexion_bd.close()
        flash("Récolte introuvable.")
        return redirect(url_for("espace_client"))

    if request.method == "POST":
        quantite_demandee = request.form["quantite_demandee"]
        message = request.form.get("message", "")

        connexion_bd.execute(
            "INSERT INTO commandes (recolte_id, client_id, quantite_demandee, message) VALUES (?, ?, ?, ?)",
            (recolte_id, session["utilisateur_id"], quantite_demandee, message)
        )
        connexion_bd.commit()
        connexion_bd.close()

        flash(f"Ta commande a été envoyée à {recolte['nom_agriculteur']}. Il te contactera pour la suite.")
        return redirect(url_for("espace_client"))

    connexion_bd.close()
    return render_template("commander.html", recolte=recolte)


@app.route("/espace-agriculteur/commandes")
def commandes_recues():
    if not utilisateur_connecte() or session["role"] != "agriculteur":
        return redirect(url_for("connexion"))

    connexion_bd = get_connexion()
    commandes = connexion_bd.execute(
        """SELECT commandes.*, recoltes.nom AS nom_recolte,
                  utilisateurs.nom AS nom_client, utilisateurs.email AS email_client
           FROM commandes
           JOIN recoltes ON commandes.recolte_id = recoltes.id
           JOIN utilisateurs ON commandes.client_id = utilisateurs.id
           WHERE recoltes.agriculteur_id = ?
           ORDER BY commandes.date_creation DESC""",
        (session["utilisateur_id"],)
    ).fetchall()
    connexion_bd.close()

    return render_template("commandes_recues.html", nom=session["nom"], commandes=commandes)


@app.route("/espace-agriculteur")
def espace_agriculteur():
    if not utilisateur_connecte() or session["role"] != "agriculteur":
        return redirect(url_for("connexion"))

    connexion_bd = get_connexion()
    recoltes = connexion_bd.execute(
        "SELECT * FROM recoltes WHERE agriculteur_id = ? ORDER BY date_creation DESC",
        (session["utilisateur_id"],)
    ).fetchall()
    connexion_bd.close()

    return render_template("espace_agriculteur.html", nom=session["nom"], recoltes=recoltes)


@app.route("/espace-agriculteur/nouvelle-recolte", methods=["GET", "POST"])
def nouvelle_recolte():
    if not utilisateur_connecte() or session["role"] != "agriculteur":
        return redirect(url_for("connexion"))

    if request.method == "POST":
        nom = request.form["nom"]
        quantite = request.form["quantite"]
        prix = request.form["prix"]
        prix_gros = request.form.get("prix_gros", "").strip() or None
        quantite_gros_min = request.form.get("quantite_gros_min", "").strip() or None
        date_disponibilite = request.form["date_disponibilite"]
        localite = request.form["localite"]
        description = request.form.get("description", "")

        fichier = request.files.get("photo")
        nom_photo = encoder_photo(fichier)

        connexion_bd = get_connexion()
        connexion_bd.execute(
            """INSERT INTO recoltes
               (agriculteur_id, nom, quantite, prix, prix_gros, quantite_gros_min,
                date_disponibilite, localite, description, photo)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (session["utilisateur_id"], nom, quantite, prix, prix_gros, quantite_gros_min,
             date_disponibilite, localite, description, nom_photo)
        )
        connexion_bd.commit()
        connexion_bd.close()

        flash("Récolte publiée avec succès.")
        return redirect(url_for("espace_agriculteur"))

    return render_template("nouvelle_recolte.html")


@app.route("/espace-agriculteur/modifier-recolte/<int:recolte_id>", methods=["GET", "POST"])
def modifier_recolte(recolte_id):
    if not utilisateur_connecte() or session["role"] != "agriculteur":
        return redirect(url_for("connexion"))

    connexion_bd = get_connexion()
    recolte = connexion_bd.execute(
        "SELECT * FROM recoltes WHERE id = ? AND agriculteur_id = ?",
        (recolte_id, session["utilisateur_id"])
    ).fetchone()

    if recolte is None:
        connexion_bd.close()
        flash("Récolte introuvable.")
        return redirect(url_for("espace_agriculteur"))

    if request.method == "POST":
        nom = request.form["nom"]
        quantite = request.form["quantite"]
        prix = request.form["prix"]
        prix_gros = request.form.get("prix_gros", "").strip() or None
        quantite_gros_min = request.form.get("quantite_gros_min", "").strip() or None
        date_disponibilite = request.form["date_disponibilite"]
        localite = request.form["localite"]
        description = request.form.get("description", "")
        statut = request.form.get("statut", "disponible")

        fichier = request.files.get("photo")
        nom_photo = encoder_photo(fichier) or recolte["photo"]

        connexion_bd.execute(
            """UPDATE recoltes SET
               nom = ?, quantite = ?, prix = ?, prix_gros = ?, quantite_gros_min = ?,
               date_disponibilite = ?, localite = ?, description = ?, photo = ?, statut = ?
               WHERE id = ? AND agriculteur_id = ?""",
            (nom, quantite, prix, prix_gros, quantite_gros_min, date_disponibilite,
             localite, description, nom_photo, statut, recolte_id, session["utilisateur_id"])
        )
        connexion_bd.commit()
        connexion_bd.close()

        flash("Récolte mise à jour.")
        return redirect(url_for("espace_agriculteur"))

    connexion_bd.close()
    return render_template("modifier_recolte.html", recolte=recolte)


@app.route("/espace-agriculteur/basculer-statut/<int:recolte_id>", methods=["POST"])
def basculer_statut(recolte_id):
    if not utilisateur_connecte() or session["role"] != "agriculteur":
        return redirect(url_for("connexion"))

    connexion_bd = get_connexion()
    recolte = connexion_bd.execute(
        "SELECT statut FROM recoltes WHERE id = ? AND agriculteur_id = ?",
        (recolte_id, session["utilisateur_id"])
    ).fetchone()

    if recolte:
        nouveau_statut = "epuise" if recolte["statut"] == "disponible" else "disponible"
        connexion_bd.execute(
            "UPDATE recoltes SET statut = ? WHERE id = ? AND agriculteur_id = ?",
            (nouveau_statut, recolte_id, session["utilisateur_id"])
        )
        connexion_bd.commit()

    connexion_bd.close()
    return redirect(url_for("espace_agriculteur"))


@app.route("/espace-fournisseur")
def espace_fournisseur():
    if not utilisateur_connecte() or session["role"] != "fournisseur":
        return redirect(url_for("connexion"))

    connexion_bd = get_connexion()
    produits = connexion_bd.execute(
        "SELECT * FROM produits_fournisseur WHERE fournisseur_id = ? ORDER BY date_creation DESC",
        (session["utilisateur_id"],)
    ).fetchall()
    connexion_bd.close()

    return render_template("espace_fournisseur.html", nom=session["nom"], produits=produits)


@app.route("/espace-fournisseur/nouveau-produit", methods=["GET", "POST"])
def nouveau_produit():
    if not utilisateur_connecte() or session["role"] != "fournisseur":
        return redirect(url_for("connexion"))

    if request.method == "POST":
        nom = request.form["nom"]
        type_produit = request.form["type_produit"]
        variete = request.form.get("variete", "").strip() or None
        duree_croissance = request.form.get("duree_croissance", "").strip() or None
        quantite = request.form["quantite"]
        prix = request.form["prix"]
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
        quantite = request.form["quantite"]
        prix = request.form["prix"]
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

    requete = """
        SELECT produits_fournisseur.*, utilisateurs.nom AS nom_fournisseur
        FROM produits_fournisseur
        JOIN utilisateurs ON produits_fournisseur.fournisseur_id = utilisateurs.id
        WHERE produits_fournisseur.statut = 'disponible'
    """
    parametres = []

    if recherche:
        requete += " AND produits_fournisseur.nom LIKE ?"
        parametres.append(f"%{recherche}%")

    if localite:
        requete += " AND produits_fournisseur.localite LIKE ?"
        parametres.append(f"%{localite}%")

    if type_produit in ("semence", "pepiniere"):
        requete += " AND produits_fournisseur.type_produit = ?"
        parametres.append(type_produit)

    requete += " ORDER BY produits_fournisseur.date_creation DESC"

    connexion_bd = get_connexion()
    produits = connexion_bd.execute(requete, parametres).fetchall()
    localites = connexion_bd.execute(
        "SELECT DISTINCT localite FROM produits_fournisseur WHERE statut = 'disponible' ORDER BY localite"
    ).fetchall()
    connexion_bd.close()

    return render_template(
        "semences_pepinieres.html", nom=session["nom"], produits=produits,
        localites=localites, recherche=recherche, localite_choisie=localite, type_choisi=type_produit
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

@app.route("/espace-financeur")
def espace_financeur():
    if not utilisateur_connecte() or session["role"] != "financeur":
        return redirect(url_for("connexion"))

    connexion_bd = get_connexion()
    offres = connexion_bd.execute(
        "SELECT * FROM offres_financement WHERE financeur_id = ? ORDER BY date_creation DESC",
        (session["utilisateur_id"],)
    ).fetchall()
    connexion_bd.close()

    return render_template("espace_financeur.html", nom=session["nom"], offres=offres)


@app.route("/espace-financeur/nouvelle-offre", methods=["GET", "POST"])
def nouvelle_offre():
    if not utilisateur_connecte() or session["role"] != "financeur":
        return redirect(url_for("connexion"))

    if request.method == "POST":
        nom = request.form["nom"]
        type_financement = request.form["type_financement"]
        montant = request.form["montant"]
        taux_conditions = request.form.get("taux_conditions", "").strip() or None
        duree = request.form.get("duree", "").strip() or None
        description = request.form.get("description", "")

        connexion_bd = get_connexion()
        connexion_bd.execute(
            """INSERT INTO offres_financement
               (financeur_id, nom, type_financement, montant, taux_conditions, duree, description)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (session["utilisateur_id"], nom, type_financement, montant, taux_conditions, duree, description)
        )
        connexion_bd.commit()
        connexion_bd.close()

        flash("Offre publiée avec succès.")
        return redirect(url_for("espace_financeur"))

    return render_template("nouvelle_offre.html")


@app.route("/espace-financeur/modifier-offre/<int:offre_id>", methods=["GET", "POST"])
def modifier_offre(offre_id):
    if not utilisateur_connecte() or session["role"] != "financeur":
        return redirect(url_for("connexion"))

    connexion_bd = get_connexion()
    offre = connexion_bd.execute(
        "SELECT * FROM offres_financement WHERE id = ? AND financeur_id = ?",
        (offre_id, session["utilisateur_id"])
    ).fetchone()

    if offre is None:
        connexion_bd.close()
        flash("Offre introuvable.")
        return redirect(url_for("espace_financeur"))

    if request.method == "POST":
        nom = request.form["nom"]
        type_financement = request.form["type_financement"]
        montant = request.form["montant"]
        taux_conditions = request.form.get("taux_conditions", "").strip() or None
        duree = request.form.get("duree", "").strip() or None
        description = request.form.get("description", "")
        statut = request.form.get("statut", "active")

        connexion_bd.execute(
            """UPDATE offres_financement SET
               nom = ?, type_financement = ?, montant = ?, taux_conditions = ?,
               duree = ?, description = ?, statut = ?
               WHERE id = ? AND financeur_id = ?""",
            (nom, type_financement, montant, taux_conditions, duree, description,
             statut, offre_id, session["utilisateur_id"])
        )
        connexion_bd.commit()
        connexion_bd.close()

        flash("Offre mise à jour.")
        return redirect(url_for("espace_financeur"))

    connexion_bd.close()
    return render_template("modifier_offre.html", offre=offre)


@app.route("/espace-financeur/basculer-statut-offre/<int:offre_id>", methods=["POST"])
def basculer_statut_offre(offre_id):
    if not utilisateur_connecte() or session["role"] != "financeur":
        return redirect(url_for("connexion"))

    connexion_bd = get_connexion()
    offre = connexion_bd.execute(
        "SELECT statut FROM offres_financement WHERE id = ? AND financeur_id = ?",
        (offre_id, session["utilisateur_id"])
    ).fetchone()

    if offre:
        nouveau_statut = "fermee" if offre["statut"] == "active" else "active"
        connexion_bd.execute(
            "UPDATE offres_financement SET statut = ? WHERE id = ? AND financeur_id = ?",
            (nouveau_statut, offre_id, session["utilisateur_id"])
        )
        connexion_bd.commit()

    connexion_bd.close()
    return redirect(url_for("espace_financeur"))


@app.route("/espace-financeur/interets-recus")
def interets_recus():
    if not utilisateur_connecte() or session["role"] != "financeur":
        return redirect(url_for("connexion"))

    connexion_bd = get_connexion()
    interets = connexion_bd.execute(
        """SELECT contacts_offre.*, offres_financement.nom AS nom_offre,
                  utilisateurs.nom AS nom_agriculteur, utilisateurs.email AS email_agriculteur
           FROM contacts_offre
           JOIN offres_financement ON contacts_offre.offre_id = offres_financement.id
           JOIN utilisateurs ON contacts_offre.agriculteur_id = utilisateurs.id
           WHERE offres_financement.financeur_id = ?
           ORDER BY contacts_offre.date_creation DESC""",
        (session["utilisateur_id"],)
    ).fetchall()

    demandes = connexion_bd.execute(
        """SELECT demandes_financement.*, utilisateurs.nom AS nom_agriculteur, utilisateurs.email AS email_agriculteur
           FROM demandes_financement
           JOIN utilisateurs ON demandes_financement.agriculteur_id = utilisateurs.id
           WHERE demandes_financement.statut = 'ouverte'
           ORDER BY demandes_financement.date_creation DESC"""
    ).fetchall()
    connexion_bd.close()

    return render_template("interets_recus.html", nom=session["nom"], interets=interets, demandes=demandes)


@app.route("/contacter-agriculteur-demande/<int:demande_id>", methods=["GET", "POST"])
def contacter_agriculteur_demande(demande_id):
    if not utilisateur_connecte() or session["role"] != "financeur":
        return redirect(url_for("connexion"))

    connexion_bd = get_connexion()
    demande = connexion_bd.execute(
        """SELECT demandes_financement.*, utilisateurs.nom AS nom_agriculteur
           FROM demandes_financement JOIN utilisateurs ON demandes_financement.agriculteur_id = utilisateurs.id
           WHERE demandes_financement.id = ?""", (demande_id,)
    ).fetchone()

    if demande is None:
        connexion_bd.close()
        flash("Demande introuvable.")
        return redirect(url_for("interets_recus"))

    if request.method == "POST":
        message = request.form.get("message", "")
        connexion_bd.execute(
            "INSERT INTO contacts_demande (demande_id, financeur_id, message) VALUES (?, ?, ?)",
            (demande_id, session["utilisateur_id"], message)
        )
        connexion_bd.commit()
        connexion_bd.close()

        flash(f"Ton message a été envoyé à {demande['nom_agriculteur']}.")
        return redirect(url_for("interets_recus"))

    connexion_bd.close()
    return render_template("contacter_agriculteur_demande.html", demande=demande)


# ---------- Financement côté Agriculteur ----------

@app.route("/espace-agriculteur/financement")
def espace_financement_agriculteur():
    if not utilisateur_connecte() or session["role"] != "agriculteur":
        return redirect(url_for("connexion"))

    connexion_bd = get_connexion()
    offres = connexion_bd.execute(
        """SELECT offres_financement.*, utilisateurs.nom AS nom_financeur
           FROM offres_financement JOIN utilisateurs ON offres_financement.financeur_id = utilisateurs.id
           WHERE offres_financement.statut = 'active'
           ORDER BY offres_financement.date_creation DESC"""
    ).fetchall()

    mes_demandes = connexion_bd.execute(
        "SELECT * FROM demandes_financement WHERE agriculteur_id = ? ORDER BY date_creation DESC",
        (session["utilisateur_id"],)
    ).fetchall()
    connexion_bd.close()

    return render_template(
        "financement_agriculteur.html", nom=session["nom"], offres=offres, mes_demandes=mes_demandes
    )


@app.route("/financement/contacter-offre/<int:offre_id>", methods=["GET", "POST"])
def contacter_offre(offre_id):
    if not utilisateur_connecte() or session["role"] != "agriculteur":
        return redirect(url_for("connexion"))

    connexion_bd = get_connexion()
    offre = connexion_bd.execute(
        """SELECT offres_financement.*, utilisateurs.nom AS nom_financeur
           FROM offres_financement JOIN utilisateurs ON offres_financement.financeur_id = utilisateurs.id
           WHERE offres_financement.id = ?""", (offre_id,)
    ).fetchone()

    if offre is None:
        connexion_bd.close()
        flash("Offre introuvable.")
        return redirect(url_for("espace_financement_agriculteur"))

    if request.method == "POST":
        message = request.form.get("message", "")
        connexion_bd.execute(
            "INSERT INTO contacts_offre (offre_id, agriculteur_id, message) VALUES (?, ?, ?)",
            (offre_id, session["utilisateur_id"], message)
        )
        connexion_bd.commit()
        connexion_bd.close()

        flash(f"Ton message a été envoyé à {offre['nom_financeur']}.")
        return redirect(url_for("espace_financement_agriculteur"))

    connexion_bd.close()
    return render_template("contacter_offre.html", offre=offre)


@app.route("/financement/nouvelle-demande", methods=["GET", "POST"])
def nouvelle_demande_financement():
    if not utilisateur_connecte() or session["role"] != "agriculteur":
        return redirect(url_for("connexion"))

    if request.method == "POST":
        objet = request.form["objet"]
        montant_souhaite = request.form["montant_souhaite"]
        description = request.form.get("description", "")

        connexion_bd = get_connexion()
        connexion_bd.execute(
            "INSERT INTO demandes_financement (agriculteur_id, objet, montant_souhaite, description) VALUES (?, ?, ?, ?)",
            (session["utilisateur_id"], objet, montant_souhaite, description)
        )
        connexion_bd.commit()
        connexion_bd.close()

        flash("Ta demande de financement a été publiée.")
        return redirect(url_for("espace_financement_agriculteur"))

    return render_template("nouvelle_demande_financement.html")


if __name__ == "__main__":
    app.run(debug=True, port=5000)
