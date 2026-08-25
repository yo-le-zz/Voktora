"""
Régression : `theme_manager.py` calcule `THEMES_DIR = core.get_data_dir() /
"themes"` au niveau module — donc dès l'import, avant qu'aucune fixture
par-test ne puisse patcher `get_data_dir`. Comme `ui_dialogs` et `ui_main`
importent `theme_manager` en cascade, le simple fait d'importer l'un de
ces packages pendant les tests créait un vrai dossier `voktora/data/` sur
le disque (à côté du code source), en dehors de toute isolation.

Ce test vérifie que le dossier de données utilisé pendant les tests n'est
JAMAIS celui du dépôt (`voktora/data`) — voir le patch de session dans
`conftest.py`.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "voktora"))

pytest.importorskip("PySide6")

import core  # noqa: E402

_REPO_VOKTORA_DIR = Path(__file__).resolve().parent.parent / "voktora"


class TestNoRealDataDirPollution:
    def test_get_data_dir_never_points_inside_repo_during_tests(self):
        assert core.get_data_dir() != _REPO_VOKTORA_DIR / "data"

    def test_repo_data_dir_does_not_exist_on_disk(self):
        # Si ce test échoue, un import ou un appel quelque part a recréé
        # le vrai dossier voktora/data au lieu d'utiliser l'isolation.
        assert not (_REPO_VOKTORA_DIR / "data").exists()

    def test_importing_ui_dialogs_does_not_touch_repo_data_dir(self):
        import ui_dialogs  # noqa: F401
        assert not (_REPO_VOKTORA_DIR / "data").exists()

    def test_importing_ui_main_does_not_touch_repo_data_dir(self):
        import ui_main  # noqa: F401
        assert not (_REPO_VOKTORA_DIR / "data").exists()
