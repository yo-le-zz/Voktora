# Projets, catégories, import et clone

Depuis la version 1.0.3, Voktora ne distingue plus « instances » et « intents » : tout est un
**projet**. On les classe avec des **catégories** que vous créez, ou par **organisation GitHub**.

## Projets

Un projet est un dossier enregistré dans `config.json` (liste `projects`). Les nouveaux projets
sont créés dans `{disque}/Voktora/Projects` — ou dans le dossier choisi via
*Paramètres → Emplacement de stockage*. Les projets existants ne sont jamais déplacés.

| Action | Où |
|--------|----|
| Nouveau projet (nom, catégorie, `git init`, dépôt GitHub) | `Ctrl+N` · Fichier → Nouveau projet |
| Importer un dossier ou un ZIP | `Ctrl+I` · Fichier → Importer · glisser-déposer sur la fenêtre |
| Cloner un dépôt GitHub | Fichier → Cloner · bouton 🐙 |
| Retirer de Voktora (fichiers conservés) / supprimer le dossier | Panneau projet → Supprimer |

## Importer

L'import tourne dans un thread : une fenêtre affiche la progression réelle et permet d'annuler.
Une annulation ou une erreur ne laisse aucun dossier partiel, et le dossier source n'est jamais
modifié avant qu'une copie complète n'ait réussi.

**Archive ZIP** — si l'archive contient un dossier racine unique, son contenu devient le projet
(nom proposé = ce dossier) ; sinon les fichiers sont rangés dans un dossier portant le nom de
l'archive. Les liens symboliques sont ignorés.

**Dossier** — trois modes :

| Mode | Effet |
|------|-------|
| Déplacer (défaut) | Le dossier est déplacé dans `Projects`. Sur un même disque c'est instantané ; entre deux disques il est copié puis la source est supprimée. Refusé pour une racine de disque ou votre dossier personnel. |
| Copier | Copie dans `Projects`, la source reste en place. |
| Ajouter sur place | Enregistre le dossier tel quel, sans rien déplacer. |

Si le dossier contient un `.git`, l'URL d'`origin` (sans identifiants) et la branche sont reprises :
le projet est alors rattaché à son organisation GitHub.

## Catégories

*Édition → Gérer les catégories* (ou le bouton 📂 de la liste) : nom, emoji, couleur, ordre.
Un projet appartient à une catégorie ; utilisez les tags pour des critères supplémentaires.

- **Classer** : glisser un ou plusieurs projets sur une catégorie (vue liste), ou clic droit →
  *Catégorie* (listes et grille). Ctrl/Maj-clic pour sélectionner plusieurs projets.
- **Renommer** une catégorie met à jour tous ses projets ; la **supprimer** les laisse « sans catégorie ».
- **Depuis GitHub** : le bouton *Créer des catégories depuis les organisations GitHub* crée une
  catégorie par propriétaire de dépôt et y range les projets (seulement ceux sans catégorie, sauf si
  la case « Inclure les projets qui ont déjà une catégorie » est cochée).

## Regrouper et trier

Le sélecteur au-dessus de la liste regroupe par **catégorie**, **organisation GitHub**, **langage**,
**statut** ou pas du tout. Le tri s'applique à l'intérieur de chaque groupe ; *Ordre manuel* conserve
l'ordre obtenu en glissant les projets. Le choix est mémorisé. Les groupes se replient.

Le regroupement par organisation est déduit de l'URL du dépôt (`github.com/<organisation>/…`), il ne
demande aucune connexion. Il n'est pas possible d'y déposer un projet : liez-le d'abord à un dépôt.

## Cloner depuis GitHub

L'onglet *Mes dépôts* liste les dépôts de votre compte, de vos organisations et ceux où vous
collaborez, filtrables par propriétaire et par texte. L'onglet *Par URL* accepte n'importe quelle URL
`https://`, `ssh://` ou `git@hôte:chemin`. Vous choisissez le nom, la branche et la catégorie
(ou « selon l'organisation GitHub »).

> Voktora ne demande que le scope `repo`. GitHub réserve `GET /user/orgs` aux scopes `user` /
> `read:org` : les organisations sont donc déduites des dépôts accessibles. Une organisation dont
> aucun dépôt n'est visible n'apparaît pas.

## Compte & organisations

*GitHub → Compte & organisations* affiche le compte connecté, les propriétaires de vos dépôts et de
vos projets (avec le nombre de chacun), et classe vos projets par organisation en un clic.

## Migration depuis 1.0.2

Au premier lancement, `instances` et `intents` sont fusionnés dans `projects` (les instances passent
avant les intents en cas de doublon), la racine de stockage devient unique et les catégories déjà
utilisées sont conservées. L'ancien fichier est copié dans `config.pre-v9.json` (à côté de `config.json`).
