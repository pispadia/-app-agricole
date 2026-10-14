// Service worker d'App Agricole : rend l'application installable et affiche une
// page « hors ligne » quand il n'y a pas de réseau. Les pages personnelles
// (commandes, profil...) ne sont jamais mises en cache, sauf le formulaire de
// publication, gardé pour pouvoir préparer une annonce au champ sans réseau.
const CACHE = "app-agricole-v2";
const PAGES_HORS_LIGNE = ["/espace-agriculteur/nouvelle-recolte"];
const FICHIERS = ["/hors-ligne", "/static/icones/icone-192.png"];

self.addEventListener("install", (evenement) => {
    evenement.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(FICHIERS)));
    self.skipWaiting();
});

self.addEventListener("activate", (evenement) => {
    evenement.waitUntil(
        caches.keys().then((noms) =>
            Promise.all(noms.filter((nom) => nom !== CACHE).map((nom) => caches.delete(nom)))
        ).then(() => self.clients.claim())
    );
});

self.addEventListener("fetch", (evenement) => {
    const requete = evenement.request;
    const adresse = new URL(requete.url);
    if (requete.method !== "GET" || adresse.origin !== self.location.origin) return;

    if (requete.mode === "navigate") {
        const aGarder = PAGES_HORS_LIGNE.includes(adresse.pathname);
        evenement.respondWith(
            fetch(requete).then((reponse) => {
                // Formulaire de publication : copie à jour gardée pour l'utiliser sans réseau
                if (aGarder && reponse.ok && !reponse.redirected) {
                    const copie = reponse.clone();
                    caches.open(CACHE).then((cache) => cache.put(adresse.pathname, copie));
                }
                return reponse;
            }).catch(() =>
                (aGarder ? caches.match(adresse.pathname) : Promise.resolve(null))
                    .then((enCache) => enCache || caches.match("/hors-ligne"))
            )
        );
    } else if (adresse.pathname.startsWith("/static/")) {
        // Feuille de style, scripts, icônes : servis du cache, mis à jour en arrière-plan
        evenement.respondWith(
            caches.open(CACHE).then((cache) => cache.match(requete).then((enCache) => {
                const reseau = fetch(requete).then((reponse) => {
                    if (reponse.ok) cache.put(requete, reponse.clone());
                    return reponse;
                }).catch(() => enCache);
                return enCache || reseau;
            }))
        );
    }
});

// Notifications push : affichées même quand l'application est fermée
self.addEventListener("push", (evenement) => {
    let donnees = {};
    try { donnees = evenement.data ? evenement.data.json() : {}; } catch (e) { donnees = {texte: evenement.data.text()}; }
    evenement.waitUntil(self.registration.showNotification(donnees.titre || "App Agricole", {
        body: donnees.texte || "",
        icon: "/static/icones/icone-192.png",
        badge: "/static/icones/icone-192.png",
        data: {url: donnees.url || "/"},
    }));
});

self.addEventListener("notificationclick", (evenement) => {
    evenement.notification.close();
    const url = new URL(evenement.notification.data.url || "/", self.location.origin).href;
    evenement.waitUntil(
        self.clients.matchAll({type: "window", includeUncontrolled: true}).then((fenetres) => {
            for (const fenetre of fenetres) {
                if ("focus" in fenetre) { fenetre.navigate(url); return fenetre.focus(); }
            }
            return self.clients.openWindow(url);
        })
    );
});
