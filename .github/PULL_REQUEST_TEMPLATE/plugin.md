<!-- Utilisez ce modèle avec : ?template=plugin.md à la fin de l'URL de la Pull Request -->
## Plugin proposé

- **Nom / id :** 
- **Nouveau plugin ou mise à jour ?** 
- **Ce qu'il fait (1-2 phrases) :** 

## Permissions demandées

<!-- Pour chaque permission déclarée dans plugin.json, dites POURQUOI elle est nécessaire. -->
| Permission | Pourquoi |
|---|---|
| `ui` | |

## Liste de contrôle

- [ ] `python tools/plugin_tool.py validate <id>` passe sans erreur
- [ ] Le plugin vit dans `marketplace/plugins/<id>/` avec `plugin.json` + `main.py`
- [ ] `version` augmentée si c'est une mise à jour
- [ ] Aucune dépendance à installer (bibliothèque standard + PySide6 uniquement)
- [ ] Pas de code obfusqué, pas d'envoi de données sans permission `network` expliquée ci-dessus
- [ ] J'ai testé le plugin dans Voktora (Paramètres → Plugins → Installer depuis un dossier)
- [ ] J'accepte que ce code soit publié sous la licence MIT du dépôt

<!-- Ne modifiez pas marketplace/index.json : il est régénéré automatiquement après la fusion. -->
