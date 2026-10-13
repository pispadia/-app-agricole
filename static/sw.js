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
