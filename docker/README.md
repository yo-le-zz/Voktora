# Compilation Voktora via Docker (usage local optionnel)

**La CI GitHub Actions n'utilise plus Docker du tout** (voir
`.github/workflows/build-release.yml`, job `build`) : elle compile
directement sur les runners `ubuntu-latest`/`windows-latest`, qui incluent
déjà les outils nécessaires. Deux raisons à ça :

1. Le `.msi` Windows ne peut de toute façon pas être compilé via Docker en
   CI : Docker Desktop n'est pas installé sur les runners `windows-latest`
   hébergés par GitHub (confirmé par [cette discussion officielle
   GitHub](https://github.com/orgs/community/discussions/148737)).
2. Pour rester cohérent entre Linux et Windows plutôt que de mélanger deux
   approches différentes, la CI compile désormais les deux nativement.

Les deux `Dockerfile` ci-dessous restent dans le dépôt pour qui veut un
environnement de compilation reproductible **en local**, mais ne sont plus
la méthode utilisée pour produire les releases.

## Linux (.deb)

```bash
docker build -f docker/linux.Dockerfile -t voktora-build-linux .
docker run --rm -v "$PWD/dist:/app/dist" voktora-build-linux 1.0.2
```

> ⚠️ Ce Dockerfile a un problème connu non résolu : sur l'image officielle
> `python:3.13-slim-bookworm`, Nuitka échoue à détecter le compilateur GCC
> installé (`x86_64-conda-linux-gnu-gcc`), même avec `CC=gcc` explicite dans
> l'image. C'est un problème documenté côté Nuitka
> ([Nuitka/Nuitka#328](https://github.com/Nuitka/Nuitka/issues/328),
> [#1212](https://github.com/Nuitka/Nuitka/issues/1212)) lié à la façon dont
> cette image Python particulière a été construite. Non résolu à ce jour —
> compiler Linux directement sur la machine (sans Docker) fonctionne
> normalement.

## Windows (.msi)

Necessite un hote Docker configure en mode "Windows containers"
(Docker Desktop : clic droit sur l'icone -> *Switch to Windows containers*).

```powershell
docker build -f docker/windows.Dockerfile -t voktora-build-windows .
docker run --rm -v "$PWD\dist:C:\app\dist" voktora-build-windows 1.0.2
```

Le paquet est ecrit dans `dist\windows\Voktora_1.0.2_x64.msi`.

## Pourquoi Docker (pour Linux) ?

- Environnement de compilation identique pour tous (memes versions de
  Nuitka, dependances systeme), evitant les ecarts entre postes de
  developpeurs et le CI.
- Le `Dockerfile` documente explicitement chaque dependance necessaire,
  ce qui remplace la configuration manuelle precedente.
- La meme image est utilisee par le workflow GitHub Actions
  (`.github/workflows/build-release.yml`), qui ne fait qu'appeler
  `docker build` / `docker run` au lieu d'installer les outils directement
  sur le runner.

## A propos de la fiabilite du .msi

Le `.msi` genere n'est pas signe numeriquement (aucun certificat de
signature de code n'est configure pour ce projet). C'est la raison pour
laquelle Windows SmartScreen ou certains antivirus peuvent le signaler
comme provenant d'un editeur non reconnu : ce n'est pas un defaut du
paquet lui-meme, Nuitka et WiX ne produisent aucun code malveillant.
Docker garantit la reproductibilite de la compilation mais ne resout pas
ce point ; la seule solution definitive est l'achat d'un certificat de
signature de code (EV ou OV) et l'ajout d'une etape `signtool` dans
`Installers/MSI installer/build_msi.py`.
