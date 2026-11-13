# Dépendances entre plugins

```json
"dependencies": {"api-plus": ">=1.0.0"}
```
* Voktora charge les plugins dans l'ordre des dépendances et **refuse** de charger un plugin dont une dépendance manque ou
  est trop ancienne (message explicite).
* Installer depuis le marketplace installe aussi les dépendances (confirmées, avec leurs permissions).
* Désactiver un plugin désactive en cascade ses dépendants ; le réactiver les remet.
* **Mises à jour automatiques** (Plugins → case « Mises à jour automatiques », activée par défaut, 12 h max) : sautées si la
  nouvelle version demande une permission de plus ou casserait un dépendant — elles sont alors proposées, pas imposées.

Publier des fonctions pour d'autres plugins :
```python
def on_load(api):
    api.provide(MonService())          # objet quelconque
# autre plugin
svc = api.plugin("mon-service")        # None-sûr : api.has_plugin("mon-service")
```
Voir le plugin **API Plus** (`marketplace/plugins/api-plus`).
