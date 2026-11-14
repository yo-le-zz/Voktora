# LOC Counter (Rust)

Compte les lignes de **code**, de **commentaires** et **vides** du projet ouvert, par langage (≈ 25 langages reconnus par extension).
Menu **Outils › Compter les lignes de code**.

* Plugin **natif** (Rust) : aucun bac à sable — voir `doc/plugins/RUST.md`. Il ne lit que le projet ouvert et n'écrit rien.
* Première installation : Voktora compile le plugin (cargo requis, quelques minutes).
* Les commentaires sont détectés de façon simple (début de ligne) : un commentaire en fin de ligne de code compte comme du code,
  et les chaînes multilignes Python ne sont pas des commentaires. Les chiffres sont des ordres de grandeur fiables, pas un audit.
* Les liens symboliques ne sont pas suivis ; les fichiers binaires sont ignorés.
