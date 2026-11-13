"""L'entrée « Espace disque » et sa fenêtre ont une vraie icône (plus d'emoji dépendant de la police)."""
import icon_catalog as catalog
import icons
from PySide6.QtWidgets import QApplication


def test_disk_emoji_is_mapped():
    assert catalog.emoji_to_icon_id("💽") == "mdi:harddisk"


def test_disk_dialog_has_icon():
    _app = QApplication.instance() or QApplication([])
    assert _app is not None
    icons.load()
    from ui_dialogs.disk_dialog import DiskUsageDialog
    d = DiskUsageDialog(paths=[])
    assert not d.windowIcon().isNull()
