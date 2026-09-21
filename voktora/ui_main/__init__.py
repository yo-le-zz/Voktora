"""
Voktora — ui_main (package)

Anciennement un unique fichier ui_main.py. Découpé en :

  workers.py               — Worker, GitWorker, UpdateCheckWorker,
                              OAuthPollWorker, _make_sep (TaskWorker vient de task_worker.py)
  task_dialog.py           — TaskDialog : fenêtre de progression avec annulation
  import_dialog.py         — ImportDialog : import d'un dossier ou d'un ZIP
  clone_dialog.py          — CloneDialog : clone depuis ses dépôts GitHub ou une URL
  repo_picker.py           — RepoPicker : liste de dépôts filtrable par organisation
  github_dialog.py         — GitHubDialog : compte, organisations, classement automatique
  github_login_dialog.py   — GitHubLoginDialog (assistant de connexion)
  token_password_dialog.py — TokenPasswordDialog
  push_dialog.py           — PushDialog
  create_dialog.py         — CreateDialog
  storage_dialog.py        — StorageDialog
  diagnostic_dialog.py     — DiagnosticDialog
  uninstall_dialog.py      — UninstallDialog
  git_dialog.py            — GitDialog
  main_window.py           — MainWindow (fenêtre principale)

La constante `STYLE` (une feuille de style QSS de ~240 lignes) présente
dans l'ancien fichier n'a pas été reprise : elle n'était appliquée nulle
part dans le code (le style réel vient de theme_manager.apply_theme_to_app,
appelé depuis main.py) — c'était du code mort.

Seule `MainWindow` était importée depuis l'extérieur du fichier d'origine
(voir main.py) ; c'est donc la seule classe ré-exportée ici.
"""

from __future__ import annotations

from .main_window import MainWindow

__all__ = ["MainWindow"]
