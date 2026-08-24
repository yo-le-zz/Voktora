# Compilation Voktora via Docker

Les installeurs Linux (`.deb`) et Windows (`.msi`) sont compiles dans des
images Docker dediees, afin que le build soit identique en local, entre
contributeurs, et en CI. Ceci remplace la compilation directe sur les
runners GitHub Actions.

## Linux (.deb)

```bash
docker build -f docker/linux.Dockerfile -t voktora-build-linux .
docker run --rm -v "$PWD/dist:/app/dist" voktora-build-linux 1.0.2
```

Le paquet est ecrit dans `dist/linux/voktora_1.0.2_amd64.deb`.

## Windows (.msi)

Necessite un hote Docker configure en mode "Windows containers"
(Docker Desktop : clic droit sur l'icone -> *Switch to Windows containers*).

```powershell
docker build -f docker/windows.Dockerfile -t voktora-build-windows .
docker run --rm -v "$PWD\dist:C:\app\dist" voktora-build-windows 1.0.2
```

Le paquet est ecrit dans `dist\windows\Voktora_1.0.2_x64.msi`.

## Pourquoi Docker ?

- Environnement de compilation identique pour tous (memes versions de
  Nuitka, WiX, dependances systeme), evitant les ecarts entre postes de
  developpeurs et le CI.
- Le `Dockerfile` documente explicitement chaque dependance necessaire,
  ce qui remplace la configuration manuelle precedente.
- Les memes images sont utilisees par le workflow GitHub Actions
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
