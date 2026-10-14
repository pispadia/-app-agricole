// Dictée vocale : un bouton « 🎤 Dicter » sous chaque zone de texte (description d'annonce, message,
// question au conseiller...) pour parler au lieu d'écrire. Utilise la reconnaissance vocale du
// navigateur (Chrome sur Android) ; rien n'apparaît si le téléphone ne la propose pas.
(function () {
    const Reconnaissance = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Reconnaissance) return;

    let enCours = null;  // une seule dictée à la fois

    function ajouterBouton(champ) {
        const bouton = document.createElement("button");
        bouton.type = "button";
        bouton.className = "btn-clair btn-petit bouton-dictee";
        bouton.textContent = "🎤 Dicter";
        bouton.title = "Parle : ton texte s'écrit tout seul";
        champ.insertAdjacentElement("afterend", bouton);

        bouton.addEventListener("click", () => {
            if (enCours) {
                enCours.stop();
                return;
            }
            const reconnaissance = new Reconnaissance();
            reconnaissance.lang = "fr-FR";
            reconnaissance.interimResults = false;
            reconnaissance.maxAlternatives = 1;
            reconnaissance.onresult = (evenement) => {
                const texte = Array.from(evenement.results).map((r) => r[0].transcript).join(" ").trim();
                if (!texte) return;
                const debut = champ.value && !/\s$/.test(champ.value) ? champ.value + " " : champ.value;
                const nouveau = debut + texte.charAt(0).toUpperCase() + texte.slice(1);
                champ.value = champ.maxLength > 0 ? nouveau.slice(0, champ.maxLength) : nouveau;
                champ.dispatchEvent(new Event("input", {bubbles: true}));
            };
            reconnaissance.onerror = (evenement) => {
                if (evenement.error === "not-allowed" || evenement.error === "service-not-allowed") {
                    alert("Autorise le micro pour App Agricole dans les réglages du navigateur, puis réessaie.");
                } else if (evenement.error === "network") {
                    alert("La dictée a besoin d'internet. Réessaie quand le réseau revient.");
                }
            };
            reconnaissance.onend = () => {
                enCours = null;
                bouton.textContent = "🎤 Dicter";
                bouton.classList.remove("ecoute");
            };
            try {
                reconnaissance.start();
            } catch (e) {
                return;
            }
            enCours = reconnaissance;
            bouton.textContent = "⏹ J'écoute… (touche pour arrêter)";
            bouton.classList.add("ecoute");
        });
    }

    function installer() {
        document.querySelectorAll("textarea:not([data-sans-dictee]), input[data-dictee]").forEach(ajouterBouton);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", installer);
    } else {
        installer();
    }
})();
