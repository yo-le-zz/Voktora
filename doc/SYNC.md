# Synchronisation entre PC (1.0.7)

Travaillez sur votre PC fixe **et** sur votre portable (même sous une autre distribution Linux) avec les mêmes
réglages et projets. Menu **Outils → 🔄 Synchronisation entre PC**.

## Principe

- Un PC est **principal** (désigné dans la fenêtre) : il gagne en cas de conflit.
- La synchronisation n'a lieu que si l'autre PC est **sur le même réseau** : LAN privé (192.168/10/172.16) ou
  **Tailscale** (100.64.0.0/10, IP stables). Aucune adresse publique n'est acceptée.
- Un secondaire se synchronise dès qu'il voit le principal ; le principal peut le lui demander.
- Si un PC s'éteint ou perd le réseau : arrêt propre, **reprise automatique** au retour (l'état déjà échangé est
  conservé). Le pourcentage des deux PC est visible dans la barre d'état et dans la fenêtre.

## Mise en route

1. Installez Voktora sur les deux PC (`.deb`, `.rpm` ou `.pkg.tar.zst` pour Arch/Omarchy).
2. PC principal : *Synchronisation → Créer un code d'appairage* (valable 10 min, usage unique).
3. Portable : *Saisir un code* → collez-le. Le PC qui a créé le code devient principal (modifiable).
4. Ouvrez le port TCP **47821** (réglable) dans le pare-feu si nécessaire (l'interface Tailscale est en général
   déjà autorisée).

## Ce qui est synchronisé

Réglages, actions rapides, catégories et statuts, métadonnées des projets, fichiers des projets (+ `.git` en bloc),
réglages des plugins. **Jamais** : jetons, mots de passe, coffre, compte GitHub, géométrie de fenêtre, chemins
locaux. Chaque catégorie, projet, motif d'exclusion, taille max est configurable.

## Règles de fusion

| Situation | Résultat |
|---|---|
| Modifié d'un seul côté (ou supprimé) | copié de l'autre côté |
| A modifié ici, B modifié là-bas | les deux modifications sont appliquées |
| Même fichier texte modifié des deux côtés, sans chevauchement | fusion 3 voies des lignes |
| Chevauchement / binaire | le principal gagne ; l'autre version reste en `….sync-conflict-…` |
| Contenus différents au premier échange | Voktora demande : ce PC / l'autre PC / le principal gagne |
| Dossier `.git` en conflit | tout le bloc suit le principal |
| Suppression | propagée ; fichiers récupérables 30 jours dans la corbeille de synchro |

## Sécurité

Code d'appairage à usage unique ; requêtes signées HMAC-SHA256 (horodatage ±2 min, nonce anti-rejeu) ; contenu
chiffré AES-256-GCM lié à chaque requête ; chemins validés (pas de `..`, ni lien symbolique sortant) ; `.git/config`
et `.git/hooks` jamais synchronisés ; un seul pair écrit à la fois. Les secrets d'appairage sont dans
`sync/settings.json` (0600), jamais dans `config.json`.
Les réglages des plugins peuvent contenir des secrets propres à ces plugins : désactivez la catégorie si besoin.
