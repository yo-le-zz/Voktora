# Mise à jour de Voktora

Voktora consulte (au plus une fois par 24 h, 8 s après le démarrage) les versions GitHub de `yo-le-zz/Voktora`
(tags `vX.Y.Z`, pré-versions ignorées). Si une version plus récente existe, il propose de **télécharger** le fichier
correspondant à votre système ; le fichier doit avoir une somme SHA-256 publiée (champ `digest` de GitHub ou ressource
`<fichier>.sha256`), sinon il est refusé. Voktora ne remplace jamais son propre programme en marche : il vous indique
le fichier vérifié à installer. Menu Préférences → « Rechercher une mise à jour… » pour vérifier à la main ;
réglage `updates.check = false` pour désactiver la vérification automatique.

## Installation en arrière-plan (1.1.3)

Après téléchargement vérifié, Voktora propose d'**installer maintenant** : il écrit un script (`voktora/update_install.py`) dans le dossier de téléchargement et le lance
détaché, puis se ferme. Le script : vérifie l'architecture du fichier (x86_64/arm64…) et celle de la machine, arrête Voktora (TERM puis KILL),
installe selon le type (`.rpm` via dnf/zypper, `.deb` via apt, `.pkg.tar.zst` via pacman, AppImage, tar, `.msi`/`.exe` sous Windows) avec `pkexec` ou `sudo -n`,
réessaie une fois, écrit `update.log`, notifie (notify-send/zenity) et **relance l'ancienne version si l'installation échoue**.
`VOKTORA_UPDATE_DRYRUN=1` affiche les commandes sans les exécuter. Le script PowerShell (Windows) n'a pas été testé sous Windows.
