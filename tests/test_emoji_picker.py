import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "voktora"))

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import ui_dialogs  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)


class TestEmojiPickerDialog:
    def test_search_finds_matching_emoji_by_keyword(self):
        dlg = ui_dialogs.EmojiPickerDialog()
        dlg._search.setText("rapide")
        assert dlg._tabs.isTabVisible(dlg._search_tab_index)
        assert dlg._search_grid.count() >= 1

    def test_empty_search_hides_results_tab(self):
        dlg = ui_dialogs.EmojiPickerDialog()
        dlg._search.setText("rapide")
        dlg._search.setText("")
        assert not dlg._tabs.isTabVisible(dlg._search_tab_index)

    def test_search_with_no_match_shows_empty_grid_message(self):
        dlg = ui_dialogs.EmojiPickerDialog()
        dlg._search.setText("zzzznomatchzzzz")
        assert dlg._search_grid.count() == 1  # le label "Aucun résultat."

    def test_choosing_emoji_sets_selection_and_accepts(self):
        dlg = ui_dialogs.EmojiPickerDialog()
        assert dlg.get_selected_emoji() is None
        dlg._choose("🚀")
        assert dlg.get_selected_emoji() == "🚀"
        assert dlg.result() == ui_dialogs.EmojiPickerDialog.Accepted
