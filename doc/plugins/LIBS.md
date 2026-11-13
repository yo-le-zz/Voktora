# Bibliothèques Python par plugin

```json
"requires": ["rich>=13,<14", "pillow"], "permissions": ["libs", "ui"]
```
Installées (uv, sinon pip, **wheels uniquement**) dans `plugins_data/<id>/libs` à la première charge, en arrière-plan ;
une empreinte évite de réinstaller. Deux plugins peuvent exiger des **versions différentes** de la même bibliothèque :
pendant le chargement et les appels du plugin, `sys.path`/`sys.modules` sont échangés.

Limites honnêtes : l'isolement repose sur cet échange — une bibliothèque qui garde un état global partagé avec du code natif,
ou deux versions passées l'une à l'autre en objets, peut se comporter mal. Les bibliothèques sont du code exécuté avec
vos droits : permission `libs` visible à l'installation. Pas de réseau → pas d'installation (message dans la console).
