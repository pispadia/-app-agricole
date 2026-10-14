// Publier une annonce sans réseau (au champ) : si le téléphone est hors connexion au moment de
// publier, l'annonce (photos comprises) est gardée sur le téléphone, puis envoyée toute seule dès
// que le réseau revient, sur n'importe quelle page de l'application.
(function () {
    const BASE = "app-agricole", MAGASIN = "annonces";
    const ADRESSE = "/espace-agriculteur/nouvelle-recolte";

    function ouvrir() {
        return new Promise((resoudre, rejeter) => {
            const demande = indexedDB.open(BASE, 1);
            demande.onupgradeneeded = () => demande.result.createObjectStore(MAGASIN, {keyPath: "id", autoIncrement: true});
            demande.onsuccess = () => resoudre(demande.result);
            demande.onerror = () => rejeter(demande.error);
        });
    }

    async function operation(mode, action) {
        const base = await ouvrir();
        return new Promise((resoudre, rejeter) => {
            const transaction = base.transaction(MAGASIN, mode);
            const resultat = action(transaction.objectStore(MAGASIN));
            transaction.oncomplete = () => resoudre(resultat && resultat.result);
            transaction.onerror = () => rejeter(transaction.error);
        });
    }

    const lister = () => operation("readonly", (magasin) => magasin.getAll());
    const ajouter = (annonce) => operation("readwrite", (magasin) => magasin.add(annonce));
    const supprimer = (id) => operation("readwrite", (magasin) => magasin.delete(id));

    function bandeau(texte, lien) {
        let element = document.getElementById("bandeau-hors-ligne");
        if (!element) {
            element = document.createElement("div");
            element.id = "bandeau-hors-ligne";
            element.className = "flash";
            const conteneur = document.querySelector("main .conteneur");
            if (!conteneur) return;
            conteneur.prepend(element);
        }
        element.textContent = texte + " ";
        if (lien) {
            const a = document.createElement("a");
            a.href = lien.href;
            a.textContent = lien.texte;
            element.appendChild(a);
        }
    }

    // 1. Sur la page « Publier une récolte » : sans réseau, on garde l'annonce au lieu d'envoyer
    const formulaire = document.querySelector("form[data-hors-ligne]");
    if (formulaire) {
        formulaire.addEventListener("submit", async (evenement) => {
            if (navigator.onLine || !window.indexedDB) return;
            evenement.preventDefault();
            if (!formulaire.reportValidity()) return;
            const champs = [];
            for (const [nom, valeur] of new FormData(formulaire).entries()) {
                if (valeur instanceof File && !valeur.name) continue;
                champs.push([nom, valeur]);
            }
            await ajouter({champs, date: new Date().toISOString(), nom: formulaire.nom.value});
            formulaire.reset();
            bandeau("📶 Pas de réseau : ton annonce est gardée sur le téléphone. Elle sera publiée toute seule dès que le réseau revient.");
            window.scrollTo(0, 0);
        });

        // Annonce refusée lors d'un envoi précédent : on la remet dans le formulaire pour la corriger
        const brouillon = sessionStorage.getItem("annonce-a-corriger");
        if (brouillon) {
            sessionStorage.removeItem("annonce-a-corriger");
            const {champs, erreur} = JSON.parse(brouillon);
            for (const [nom, valeur] of champs) {
                const champ = formulaire.elements[nom];
                if (champ && champ.type !== "file" && nom !== "csrf_token") champ.value = valeur;
            }
            bandeau("⚠️ Ton annonce enregistrée hors connexion n'a pas pu être publiée : " + erreur + " Corrige-la puis publie (les photos sont à remettre).");
        }
    }

    // 2. Partout : dès qu'il y a du réseau, on envoie les annonces en attente
    let envoiEnCours = false;
    async function envoyer() {
        if (envoiEnCours || !navigator.onLine || !window.indexedDB) return;
        envoiEnCours = true;
        try {
            const annonces = await lister();
            if (!annonces.length) return;
            const jeton = document.querySelector('meta[name="csrf-token"]');
            let publiees = 0;
            for (const annonce of annonces) {
                const donnees = new FormData();
                for (const [nom, valeur] of annonce.champs) {
                    if (nom !== "csrf_token") donnees.append(nom, valeur);
                }
                if (jeton) donnees.append("csrf_token", jeton.content);
                let reponse;
                try {
                    reponse = await fetch(ADRESSE, {method: "POST", body: donnees, headers: {"X-Hors-Ligne": "1"}});
                } catch (e) {
                    break;  // toujours pas de réseau : on réessaiera plus tard
                }
                const resultat = await reponse.json().catch(() => ({}));
                if (reponse.ok && resultat.ok) {
                    await supprimer(annonce.id);
                    publiees += 1;
                } else if (reponse.status === 400 && resultat.erreur) {
                    // Refusée (ex : prix mal écrit) : on la rend à l'agriculteur pour qu'il la corrige
                    await supprimer(annonce.id);
                    const textes = annonce.champs.filter(([, valeur]) => typeof valeur === "string");
                    sessionStorage.setItem("annonce-a-corriger", JSON.stringify({champs: textes, erreur: resultat.erreur}));
                    bandeau("⚠️ Une annonce enregistrée hors connexion est à corriger.", {href: ADRESSE, texte: "La corriger"});
                    return;
                } else {
                    // Pas connecté, session expirée... : on garde l'annonce pour plus tard
                    bandeau("📶 " + annonces.length + " annonce(s) en attente : connecte-toi pour les publier.");
                    return;
                }
            }
            const restantes = (await lister()).length;
            if (publiees) {
                bandeau("✅ " + publiees + " annonce(s) préparée(s) hors connexion publiée(s)" + (restantes ? ", " + restantes + " en attente." : "."),
                        {href: "/espace-agriculteur", texte: "Voir mes annonces"});
            } else if (restantes) {
                bandeau("📶 " + restantes + " annonce(s) en attente d'envoi : elles partiront dès que le réseau revient.");
            }
        } finally {
            envoiEnCours = false;
        }
    }

    window.addEventListener("online", envoyer);
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", envoyer);
    } else {
        envoyer();
    }
})();
