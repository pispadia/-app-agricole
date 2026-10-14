"""Espace financeur et demandes de financement des agriculteurs."""
from flask import render_template, request, redirect, url_for, session, flash
from database import get_connexion
from core import app, utilisateur_connecte, premium_requis


@app.route("/espace-financeur")
def espace_financeur():
    if not utilisateur_connecte() or session["role"] != "financeur":
        return redirect(url_for("connexion"))

    connexion_bd = get_connexion()
    offres = connexion_bd.execute(
        "SELECT * FROM offres_financement WHERE financeur_id = ? ORDER BY date_creation DESC",
        (session["utilisateur_id"],)
    ).fetchall()
    interets = connexion_bd.execute(
        """SELECT COUNT(*) AS n FROM contacts_offre
           JOIN offres_financement ON contacts_offre.offre_id = offres_financement.id
           WHERE offres_financement.financeur_id = ?""", (session["utilisateur_id"],)
    ).fetchone()["n"]
    demandes_ouvertes = connexion_bd.execute(
        "SELECT COUNT(*) AS n FROM demandes_financement WHERE statut = 'ouverte'").fetchone()["n"]
    connexion_bd.close()

    return render_template("espace_financeur.html", nom=session["nom"], offres=offres,
                           interets=interets, demandes_ouvertes=demandes_ouvertes)


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
@premium_requis
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
@premium_requis
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
