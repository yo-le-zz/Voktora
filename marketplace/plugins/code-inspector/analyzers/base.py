"""Interface commune des analyseurs de langage + registre extensible.

Pour ajouter un langage : sous-classez `Analyzer`, renseignez `lang` et `extensions`, implémentez `analyze_file`
(texte → FileResult : symboles, références brutes, imports, problèmes), puis appelez `register(MonAnalyseur())`.
Un analyseur ne regarde QU'UN fichier : c'est ce qui rend l'analyse incrémentale ; le lieu (core/linker.py)
relie ensuite les fichiers entre eux."""

from __future__ import annotations

from ..core.model import FileResult

ANALYZER_VERSION = 3          # à incrémenter quand la sortie d'un analyseur change : invalide le cache


class Analyzer:
    lang = ""
    extensions: tuple[str, ...] = ()
    filenames: tuple[str, ...] = ()
    patterns: tuple[str, ...] = ()            # expressions régulières sur le nom de fichier (ex. requirements.*\.txt)

    def analyze_file(self, path: str, text: str) -> FileResult:
        raise NotImplementedError


_registry: dict[str, Analyzer] = {}
_by_ext: dict[str, Analyzer] = {}
_by_name: dict[str, Analyzer] = {}
_patterns: list = []


def register(analyzer: Analyzer) -> None:
    _registry[analyzer.lang] = analyzer
    for ext in analyzer.extensions:
        _by_ext[ext.lower()] = analyzer
    for name in analyzer.filenames:
        _by_name[name.lower()] = analyzer
    import re
    for pattern in analyzer.patterns:
        _patterns.append((re.compile(pattern, re.IGNORECASE), analyzer))


def for_file(path: str) -> Analyzer | None:
    name = path.rsplit("/", 1)[-1].lower()
    if name in _by_name:
        return _by_name[name]
    for pattern, analyzer in _patterns:
        if pattern.fullmatch(name):
            return analyzer
    dot = name.rfind(".")
    return _by_ext.get(name[dot:]) if dot >= 0 else None


def languages() -> list[str]:
    return sorted(_registry)
