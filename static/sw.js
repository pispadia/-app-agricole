// Service worker d'App Agricole : rend l'application installable et affiche une
// page « hors ligne » quand il n'y a pas de réseau. Les pages personnelles
// (commandes, profil...) ne sont jamais mises en cache.
const CACHE = "app-agricole-v1";
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
    if (evenement.request.mode === "navigate") {
        evenement.respondWith(
            fetch(evenement.request).catch(() => caches.match("/hors-ligne"))
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
