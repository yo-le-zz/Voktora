# Forges (1.0.8)

Menu **🌐 Forges** : un seul endroit pour GitHub, GitLab, la forge de Fedora et les autres.

- **GitHub** : connexion / organisations / clonage comme avant, mais regroupés ici.
- **GitLab** (gitlab.com ou auto-hébergé), **Fedora Forge** (`forge.fedoraproject.org`, Forgejo), **Codeberg**,
  toute instance **Forgejo / Gitea**, **GitHub Enterprise** : *Gérer les forges → Comptes → Ajouter* avec un jeton
  personnel (droit de lecture des dépôts). Le jeton est vérifié tout de suite.
- **Forks** : l'onglet Git d'un projet affiche « 🍴 fork de propriétaire/dépôt ». Détection immédiate via le remote
  `upstream`, confirmée en arrière-plan par l'API (drapeau `fork` + dépôt parent). L'onglet *Dépôts* liste ceux de
  tous vos comptes avec un filtre « Forks seulement » ; double-clic = copier l'adresse de clone.
- **Sécurité** : HTTPS uniquement, certificats vérifiés, jetons dans le coffre (Vault) quand il est déverrouillé,
  jamais écrits dans un remote ni synchronisés entre PC.
