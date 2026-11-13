# Boutiques d'apparence (Voktora 1.1.1)

Menu **Préférences → Boutiques d'apparence**. Trois boutiques, chacune avec son propre index :

| Boutique | Contenu | Fichiers |
|---|---|---|
| **Thèmes** | couleurs de toute la fenêtre | `theme.json` |
| **Icônes** | pack d'icônes SVG (les icônes absentes gardent l'original) | `<nom>.svg` (nom = icône MDI, ex. `folder.svg`) |
| **Styles** | feuille Qt (arrondis, densité, barres…) ajoutée après le thème | `*.qss` |

Les trois peuvent être combinés : un thème, un pack d'icônes, plusieurs styles. Le thème par défaut de Voktora,
les thèmes locaux et ceux fournis par des plugins (`api.register_theme`) restent disponibles.

## Sécurité
Un objet n'est que de la **donnée**, jamais du code : https obligatoire, taille bornée, noms de fichiers relatifs,
extensions limitées par boutique, empreinte **SHA-256** de chaque fichier vérifiée avant toute écriture
(installation atomique). SVG : `<script>`, `on…=`, liens externes, `<foreignObject>` refusés. QSS : `url(` et
`@import` refusés.

## Sources — « chacun son shop »
Chaque boutique lit la source officielle (`yo-le-zz/Voktora`, dossier `marketplace/shops/<type>/index.json`) plus
des sources supplémentaires :
- **vous** : bouton *Sources…* d'un onglet (adresse `https://…` d'un dépôt qui contient `shops/<type>/index.json`) ;
- **un plugin** : `api.register_shop_source("themes", "Ma boutique", "https://…")` (permission `ui`), retirée au
  déchargement du plugin.

Les plugins peuvent aussi lire `api.shop_installed(kind)` (`config.read`) et, avec confirmation de l'utilisateur,
appeler `api.set_theme(id)`, `api.set_icon_pack(id)` et `api.set_style_enabled(id, True)` (`ui`).

## Créer un objet
```
python tools/shop_tool.py new themes mon-theme
# éditez marketplace/shops/themes/items/mon-theme/{item.json,theme.json}
python tools/shop_tool.py validate && python tools/shop_tool.py build-index
```
`item.json` : `id` (= nom du dossier), `name`, `version`, `author`, `description`, `tags`, et pour un thème `colors`
(aperçu : liste de couleurs `#rrggbb`). Pour essayer sans publier : *Depuis un dossier…* dans la fenêtre.

Exemple de `theme.json` : `{"name": "…", "colors": {"base": "#0b0b1e", "text": "#f5f5ff", "blue": "#00f0ff",
"mauve": "#ff2bd6", "green": "#39ff88", "red": "#ff3860", "yellow": "#fff95b", "primary": "#ff2bd6"}}` —
Voktora complète les couleurs manquantes.

## Limites connues
Les icônes déjà affichées changent à la réouverture des fenêtres. Les objets ne sont pas encore signés
(seulement vérifiés par empreinte depuis l'index de la source).
