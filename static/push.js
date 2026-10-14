// Bouton « Activer les notifications » : abonne cet appareil aux notifications push
(function () {
    const bloc = document.getElementById("bloc-push");
    if (!bloc) return;
    const bouton = document.getElementById("bouton-push");
    const etat = document.getElementById("etat-push");
    const jeton = bloc.dataset.csrf;

    if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
        etat.textContent = "Sur iPhone, ajoute d'abord l'app à l'écran d'accueil (Partager → Sur l'écran d'accueil), puis reviens ici. Sinon, tu recevras les alertes par SMS.";
        bouton.hidden = true;
        return;
    }

    function cleEnOctets(base64) {
        const texte = atob((base64 + "=".repeat((4 - base64.length % 4) % 4)).replace(/-/g, "+").replace(/_/g, "/"));
        return Uint8Array.from(texte, (c) => c.charCodeAt(0));
    }

    function envoyer(adresse, donnees) {
        return fetch(adresse, {
            method: "POST",
            headers: {"Content-Type": "application/json", "X-CSRFToken": jeton},
            body: JSON.stringify(donnees),
        });
    }

    function afficher(actif) {
        bouton.textContent = actif ? "🔕 Désactiver sur cet appareil" : "🔔 Activer les notifications sur cet appareil";
        etat.textContent = actif ? "✅ Notifications activées sur cet appareil : plus besoin de SMS." : "";
        bouton.dataset.actif = actif ? "1" : "";
    }

    navigator.serviceWorker.ready.then((reg) => reg.pushManager.getSubscription()).then((abonnement) => {
        afficher(abonnement && Notification.permission === "granted");
    });

    bouton.addEventListener("click", async () => {
        bouton.disabled = true;
        try {
            const reg = await navigator.serviceWorker.ready;
            const existant = await reg.pushManager.getSubscription();
            if (bouton.dataset.actif && existant) {
                await envoyer("/push/desabonnement", {endpoint: existant.endpoint});
                await existant.unsubscribe();
                afficher(false);
                return;
            }
            if (await Notification.requestPermission() !== "granted") {
                etat.textContent = "Notifications refusées. Autorise-les dans les réglages du navigateur pour ce site.";
                return;
            }
            const {cle} = await (await fetch("/push/cle")).json();
            const abonnement = existant || await reg.pushManager.subscribe({
                userVisibleOnly: true, applicationServerKey: cleEnOctets(cle),
            });
            const reponse = await envoyer("/push/abonnement", abonnement.toJSON());
            if (!reponse.ok) throw new Error("abonnement refusé");
            afficher(true);
        } catch (erreur) {
            etat.textContent = "Impossible d'activer les notifications sur cet appareil.";
        } finally {
            bouton.disabled = false;
        }
    });
})();
