<!-- Utilisez ce modèle avec : ?template=community-plugin.md à la fin de l'URL de la Pull Request -->
## Plugin communautaire (sous-module Git)

- **Id du plugin :** 
- **Mon dépôt (fork) :** https://github.com/<vous>/<dépôt>
- **Nouveau plugin, ou nouvelle version d'un plugin déjà accepté ?** 
- **Ce qu'il fait (1-2 phrases) :** 
- **Ce qui a changé depuis le commit précédemment accepté (mise à jour) :** 

## Permissions demandées

| Permission | Pourquoi |
|---|---|
| `ui` | |

## Liste de contrôle

- [ ] Cette PR ne contient QUE le sous-module `marketplace/community/<id>` (+ `.gitmodules`) — rien d'autre
- [ ] `python tools/plugin_tool.py validate <id>` passe sans erreur
- [ ] `version` augmentée dans `plugin.json` si c'est une mise à jour (obligatoire quand le commit épinglé change)
- [ ] Aucune dépendance à installer (bibliothèque standard + PySide6 uniquement), pas de code obfusqué
- [ ] Je comprends que le code de mon dépôt n'est installé qu'au commit épinglé : toute modification ultérieure
      demande une NOUVELLE Pull Request, même si le plugin a déjà été accepté
- [ ] J'accepte la licence MIT pour ce plugin
