"""
Voktora — ui_dialogs (package)
Version : 1.0.2

Anciennement un unique fichier ui_dialogs.py (3226 lignes). Découpé selon
les marqueurs de section déjà présents dans le fichier d'origine (chaque
dialogue était déjà annoté par son auteur comme "════ x_dialog.py ════",
une intention de découpage jamais finalisée) :

  categories_dialog.py      — CategoriesDialog
  status_dialog.py          — StatusDialog, EditStatusDialog
  config_dialog.py          — ConfigDialog
  customize_dialog.py       — CustomizeProjectDialog
  theme_dialog.py           — CustomThemeDialog, ThemeSettingsDialog
  encrypt_dialog.py         — EncryptWorker, CopyWorker, EncryptProjectDialog
  migrate_dialog.py         — ExportWorker, ImportWorker, MigrateDialog
  master_password_dialog.py — MasterPasswordSetupDialog
  vault_dialog.py           — VaultDialog
  profiles_dialog.py        — ProfilesDialog
  hooks_dialog.py           — HooksDialog
  snapshot_dialog.py        — SnapshotDialog
  dashboard_dialog.py       — DashboardDialog
  plugins_dialog.py         — PluginsDialog

Contrairement à core/, aucune classe de ce package n'en référence une
autre ni ne partage d'état mutable au niveau module : un simple ré-export
statique par nom suffit ici (pas besoin de délégation dynamique).
Tout code existant faisant `from ui_dialogs import NomDeLaClasse` ou
`import ui_dialogs; ui_dialogs.NomDeLaClasse` continue de fonctionner
sans modification.
"""

from __future__ import annotations

from .categories_dialog import CategoriesDialog
from .config_dialog import ConfigDialog
from .customize_dialog import CustomizeProjectDialog
from .dashboard_dialog import DashboardDialog
from .emoji_picker_dialog import EmojiPickerDialog
from .encrypt_dialog import CopyWorker, EncryptProjectDialog, EncryptWorker
from .hooks_dialog import HooksDialog
from .json_config_editor_dialog import JsonConfigEditorDialog
from .master_password_dialog import MasterPasswordSetupDialog
from .migrate_dialog import ExportWorker, ImportWorker, MigrateDialog
from .plugins_dialog import PluginsDialog
from .profiles_dialog import ProfilesDialog
from .snapshot_dialog import SnapshotDialog
from .status_dialog import EditStatusDialog, StatusDialog
from .theme_dialog import CustomThemeDialog, ThemeSettingsDialog
from .vault_dialog import VaultDialog

__all__ = [
    "CategoriesDialog",
    "ConfigDialog",
    "CustomizeProjectDialog",
    "DashboardDialog",
    "EmojiPickerDialog",
    "CopyWorker", "EncryptProjectDialog", "EncryptWorker",
    "HooksDialog",
    "JsonConfigEditorDialog",
    "MasterPasswordSetupDialog",
    "ExportWorker", "ImportWorker", "MigrateDialog",
    "PluginsDialog",
    "ProfilesDialog",
    "SnapshotDialog",
    "EditStatusDialog", "StatusDialog",
    "CustomThemeDialog", "ThemeSettingsDialog",
    "VaultDialog",
]
