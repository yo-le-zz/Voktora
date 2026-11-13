# API Studio

Client HTTP pour développeurs, dans Voktora (onglet **API Studio** d'un projet, ou **Outils → API Studio…**, Ctrl+Alt+A).

- **Requêtes** : GET/POST/PUT/PATCH/DELETE/HEAD/OPTIONS, en-têtes, paramètres, cookies (jar de session), redirections, délai, corps JSON / XML / texte / formulaire / multipart (fichiers : valeur `@/chemin`).
- **Authentification** : Basic, Bearer, clé d'API (en-tête ou paramètre), OAuth2 (client_credentials dans l'interface ; briques code + **PKCE S256** : `core/auth.py` — `pkce_pair`, `authorization_url`, `token_request`, `parse_redirect` avec contrôle de `state`).
- **Collections** par projet, **environnements** et variables `{{nom}}` (+ `{{$uuid}}`, `{{$timestamp}}`, `{{$isoTimestamp}}`).
- **Chaînage** : extraire une valeur d'une réponse (JSON `$.a.b[0]`, en-tête, regex, statut) vers une variable utilisable par les requêtes suivantes ; « Lancer la collection » exécute tout dans l'ordre.
- **Tests automatiques** : statut, en-tête, JSON, corps, temps (`==`, `!=`, `contains`, `matches`, `<`, `>`, `exists`…).
- **Scripts avant/après** en Python ou JavaScript, dans un **processus isolé** (dossier temporaire vide, environnement réduit à `PATH`, délai maximal). Variables : `vars`, `request`, `response`, `log()`, `test(nom, ok)`. JavaScript nécessite Node.js ; sinon l'erreur est explicite.
- **WebSocket** (RFC 6455, `ws://` et `wss://`) : poignée de main vérifiée, fragmentation, ping/pong, fermeture.
- **Serveur mock** HTTP + écho WebSocket sur **127.0.0.1 uniquement** ; routes `{param}`, statut, en-têtes, délai, corps avec variables.
- **Import** OpenAPI 3 / Swagger 2 (JSON ; YAML si PyYAML est installé) et Postman v2.1 ; **export** Postman et JSON natif.
- **Historique** (300 dernières requêtes).

## Limites honnêtes
Les scripts isolés limitent les effets de bord (cwd, environnement, délai) mais ne sont **pas un bac à sable de sécurité** : n'exécutez que vos propres scripts. Pas de HTTP/2 ni de proxy, pas de flux SSE. OAuth2 avec redirection (code + PKCE) : briques et tests fournis, mais pas encore d'assistant graphique de connexion. Les secrets des requêtes sont stockés en clair dans le dossier de données du plugin (utilisez des variables d'environnement plutôt que de les écrire dans les collections partagées).

## Permissions
`network` (client HTTP, WebSocket, mock), `shell` (scripts isolés), `projects.read`, `ui`. Tests : `tests/test_plugin_api_studio.py` (racine du dépôt) — ils exécutent un vrai serveur mock local.
