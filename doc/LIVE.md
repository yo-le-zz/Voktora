# Mode live

Essayer Voktora sans rien installer : tout est supprimé à la fermeture.

```sh
curl -fsSL https://raw.githubusercontent.com/yo-le-zz/Voktora/main/Installers/live/install-live.sh | sh
```
Windows (non testé) : `irm https://raw.githubusercontent.com/yo-le-zz/Voktora/main/Installers/live/install-live.ps1 | iex`

## Fonctionnement
- Dossier `voktora-live-XXXXXXXX` (+ marqueur `.voktora-live`) dans le dossier temporaire ; code, Python (uv), dépendances, config, plugins, coffre, projets s'y trouvent. Rien dans `$HOME`.
- Voktora reçoit `VOKTORA_LIVE_DIR` : données via `VOKTORA_DATA_DIR`, projets dans `projects/`, pas de binaire natif Rust.
- Fermeture : exporter les projets / tout supprimer / rester. Le script supprime ensuite le dossier (aussi sur Ctrl+C, SIGTERM, SIGHUP).
- Désactivés : synchronisation, mise à jour automatique, moniteur développeur.
- Variables : `VOKTORA_LIVE_REF` (étiquette ou branche), `VOKTORA_LIVE_KEEP=1` (ne rien supprimer).

## Garde-fous
Suppression limitée à un dossier réel (pas un lien) nommé `voktora-live-<alphanum>`, avec marqueur, dans le dossier temporaire du système. Les sessions mortes (kill -9) sont nettoyées au lancement suivant.

## Limites
Archive GitHub sans somme de contrôle (HTTPS seul) ; réseau requis ; 1re exécution 1–2 min ; effacement simple (pas sécurisé) ; script Windows non testé.
