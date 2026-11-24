# J.A.R.V.I.S.

Assistant personnel sur ton PC Windows. Pilotable depuis le PC et le téléphone, à la voix, au clavier ou aux mains.

## Installation (une fois)
1. Dézippe le dossier `jarvis` où tu veux (ex : `C:\JARVIS`).
2. Clic droit sur `install.ps1` → **Exécuter avec PowerShell**.
   Si Windows bloque : ouvre PowerShell dans le dossier et tape
   `powershell -ExecutionPolicy Bypass -File install.ps1`
3. Colle ta clé API Claude quand on te la demande (console.anthropic.com → API Keys).
   Facturation séparée de l'abonnement Claude, à l'usage. Sans clé : Jarvis tourne en local uniquement.
4. Note le **code d'accès** affiché en jaune. L'interface le demande une fois par appareil.

Le script installe : Python, les dépendances, Ollama + modèle local, le suivi des mains, la reconnaissance vocale hors ligne, le démarrage automatique et Tailscale.

## Utilisation
- **PC** : `http://127.0.0.1:8765` (s'ouvre tout seul ; Jarvis démarre avec Windows).
- **Téléphone** : installe Tailscale, connecte le même compte, ouvre l'adresse `https://<ton-pc>.<...>.ts.net` affichée à la fin de l'installation. Menu du navigateur → « Ajouter à l'écran d'accueil » = appli Jarvis.
- **Voix** : touche Espace ou clic sur le réacteur → parle → Espace/clic pour envoyer. Jarvis répond à voix haute.
- **Mains** (bouton ✋, PC avec webcam) :
  - 1er clic = pilote l'interface Jarvis. Index = curseur, pincer pouce-index = clic.
  - 2e clic (🖱) = pilote la souris de Windows.
  - 3e clic = arrêt.
- **Tâches** : demande n'importe quoi (« range mes téléchargements par type », « cherche les offres d'agent de sûreté à Genève et résume-les », « ouvre Spotify »). Jarvis enchaîne les étapes.
- **Sécurité** : commandes système et écriture de fichiers = validation à l'écran. Désactivable : `CONFIRM_DANGEROUS=false` dans `.env`.

## Hors réseau
- Coupure internet → bascule automatique sur le modèle local (voyant **LOCAL** orange).
- Voix, mains, interface, commandes PC : 100 % locaux.
- Indisponible hors ligne : recherche web, Claude.
- Téléphone hors ligne : il doit être sur le même Wi-Fi que le PC (Tailscale fonctionne en réseau local).

## Fichiers
- `server.py` : serveur + API · `brain.py` : Claude / local, enchaînement des tâches · `tools.py` : actions sur le PC
- `static/` : interface HUD, voix, mains · `.env` : réglages · `data/notes.json` : ce que Jarvis retient de toi
- `jarvis.log` : journal

## Ajouter une capacité
Ajoute une fonction dans `tools.py` + une ligne dans `SPECS`. Jarvis l'utilise immédiatement après redémarrage.

## Dépannage
- Voyant **AUCUN CERVEAU** : lance `ollama serve` ou vérifie la clé dans `.env`.
- Micro/caméra refusés sur téléphone : passe bien par l'adresse `https://…ts.net`, pas par l'IP.
- Redémarrer Jarvis : Gestionnaire des tâches → terminer `pythonw.exe`, puis double-clic sur `jarvis-hidden.vbs`.

## Mises à jour automatiques
Jarvis vérifie le dépôt GitHub `aslamborz095-arch/jarvis` au démarrage puis toutes les 6 h. Nouvelle version → téléchargée, installée, redémarrage automatique. Tes réglages (`.env`), ta mémoire (`data/`) et l'environnement Python ne sont jamais touchés. Version affichée sous la date dans l'interface. Désactivable : `AUTO_UPDATE=false` dans `.env`.

## Mot d'éveil « Hey Jarvis »
Sur le PC, Jarvis écoute en permanence le micro (100 % local, rien n'est envoyé). Dis **« Hey Jarvis »** → bip → donne ton ordre → il répond à voix haute. Les échanges s'affichent aussi dans l'interface (PC et téléphone). Voyant **HEY JARVIS** vert = actif. Sensibilité : `WAKE_THRESHOLD` dans `.env` (plus bas = plus sensible). Désactiver : `WAKE_WORD=false`.

## Téléphone Android (Redmi)
Jarvis pilote le téléphone par ADB sans fil : ouvrir des applis, lire l'écran, toucher, écrire, glisser, notifications, liens, préparer appels et SMS. Association une seule fois via le bouton 📱 de l'interface (les étapes y sont décrites). Ensuite le téléphone se reconnecte tout seul quand il est sur le même Wi-Fi que le PC.

## Vitesse
Le modèle local reste chargé en mémoire et les consignes + outils sont mis en cache (préchauffage au démarrage) : seules les nouvelles phrases sont traitées. Avec une clé Claude, le cache de prompt est aussi activé.

## Gmail, Agenda, musique
- **Google** : bouton ⚙ → coller le fichier OAuth (client « Application de bureau » créé dans Google Cloud) → CONNECTER GOOGLE (sur le PC). Jarvis lit/cherche les mails, crée des brouillons, envoie (avec validation), gère l'agenda.
- **Musique** : lecture/pause/suivant/volume et recherche Spotify, sur le PC ou le téléphone.
