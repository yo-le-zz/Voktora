# Mentions légales et composants tiers — Voktora

## Éditeur et droits

Voktora est un logiciel libre créé et publié par **yolezz** (compte GitHub
[yo-le-zz](https://github.com/yo-le-zz)).

Copyright © 2026 yolezz. Distribué sous **licence MIT** (voir [LICENSE](LICENSE)).

## Absence de garantie

Voktora est fourni « tel quel », sans garantie d'aucune sorte, expresse ou implicite (voir le texte de
la licence MIT). L'utilisateur reste responsable de la sauvegarde de ses données et de la conservation
de ses secrets. Voktora n'envoie aucune donnée à l'éditeur : les seules connexions réseau sont celles
que vous déclenchez (GitHub, vérification des mises à jour sur GitHub, fournisseur d'IA que vous
configurez — Ollama, OmniRoute ou tout serveur compatible OpenAI).

## Marques

« GitHub », « Ollama », « OmniRoute », « Fedora », « Qt » et les autres noms cités appartiennent à leurs
propriétaires respectifs ; leur citation n'implique aucun partenariat ni parrainage.

## Composants tiers

| Composant | Rôle | Licence |
|-----------|------|---------|
| [PySide6 / Qt for Python](https://doc.qt.io/qtforpython-6/) | Interface graphique | LGPL-3.0 (ou GPL / commerciale) |
| [cryptography](https://github.com/pyca/cryptography) | Chiffrement (Fernet, AES-GCM, scrypt) | Apache-2.0 ou BSD-3-Clause |
| [QtAwesome](https://github.com/spyder-ide/qtawesome) | Chargement des icônes | MIT |
| [Material Design Icons](https://pictogrammers.com/library/mdi/) (police `mdi6`, via QtAwesome) | Icônes de l'interface | Apache-2.0 |
| [Nuitka](https://nuitka.net/) | Compilation des installateurs (outil de build uniquement) | Apache-2.0 |
| [PyO3](https://pyo3.rs/), [rayon](https://github.com/rayon-rs/rayon), [walkdir](https://github.com/BurntSushi/walkdir), [crc32fast](https://github.com/srijs/rust-crc32fast) | Extension native optionnelle `voktora_native` | MIT / Apache-2.0 |

### Qt et LGPL-3.0

Voktora utilise Qt via PySide6, sous licence LGPL-3.0. Les bibliothèques Qt sont liées dynamiquement
(fichiers `.so` / `.dll` fournis à côté de l'exécutable dans les paquets) : vous pouvez les remplacer
par une version modifiée de Qt, conformément à la LGPL. Le code source de Voktora est disponible sur
<https://github.com/yo-le-zz/Voktora> ; celui de Qt sur <https://code.qt.io/>.
