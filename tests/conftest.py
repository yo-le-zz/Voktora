"""
Fixtures partagées pour la suite de tests Voktora.

Le code source de Voktora (voir voktora/main.py) ajoute le dossier
`voktora/` lui-même à sys.path et importe ses modules en absolu
(`import core`, `import mc`, ...). Depuis le découpage en package,
`core` est un vrai package Python (voktora/core/__init__.py) qui délègue
dynamiquement vers ses sous-modules (config_store, paths, github_auth...)
via `__getattr__` — voir le docstring de core/__init__.py pour le détail.

Conséquence pour les tests : patcher `core.get_data_dir` (la façade) ne
suffit PAS à isoler les appels internes faits depuis l'intérieur d'un
sous-module (ex. `config_store._load_config()` appelle `get_data_dir()`
en non qualifié, résolu dans le namespace de `config_store`, pas de
`core`). Il faut donc patcher directement le sous-module PROPRIÉTAIRE
(`core.paths`, `core.config_store`, `core.github_auth`) — la façade
`core.X` reflète alors automatiquement le patch via `__getattr__`.

Isolation de base (avant même le premier test) : `theme_manager.py`
calcule `THEMES_DIR = core.get_data_dir() / "themes"` au niveau module,
donc dès son import — avant qu'aucune fixture par-test ne puisse
intervenir. Comme plusieurs fichiers de test importent `ui_dialogs` /
`ui_main` (qui importent `theme_manager` en cascade), on patche
`get_data_dir`/`get_config_path` vers un dossier temporaire de session
dès le chargement de ce conftest — avant la collecte de tout fichier de
test — pour qu'aucun import, même hors du cadre d'un test isolé
explicitement, n'écrive jamais dans le vrai dossier du projet.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "voktora"))

import core  # noqa: E402

_session_data_dir = Path(tempfile.mkdtemp(prefix="voktora-test-session-"))
core.paths.get_data_dir.cache_clear()
core.paths.get_config_path.cache_clear()
core.paths.get_data_dir = lambda: _session_data_dir
core.paths.get_config_path = lambda: _session_data_dir / core.constants.CONFIG_FILENAME


@pytest.fixture
def isolated_data_dir(tmp_path, monkeypatch):
    """Redirige core.get_data_dir()/get_config_path() vers tmp_path."""
    data_dir = tmp_path / "voktora-data"
    data_dir.mkdir()

    core.paths.get_app_dir.cache_clear()
    core.paths.get_backups_dir.cache_clear()
    monkeypatch.setattr(core.paths, "get_data_dir", lambda: data_dir)
    monkeypatch.setattr(core.paths, "get_config_path", lambda: data_dir / core.constants.CONFIG_FILENAME)
    monkeypatch.setattr(core.config_store, "_config_cache", None)
    monkeypatch.setattr(core.github_auth, "_GITHUB_SESSION", None)

    yield data_dir

    core.paths.get_app_dir.cache_clear()
    core.paths.get_backups_dir.cache_clear()