"""
Voktora — live (1.1.5) : mode « live » éphémère. Tout (configuration, plugins, boutiques, coffre, projets créés) vit dans un dossier
temporaire `voktora-live-XXXX` ; à la fermeture, TOUT est supprimé. Lancé par `install-live.sh` / `install-live.ps1` (qui suppriment
aussi le code téléchargé et l'environnement Python), ou à la main : `VOKTORA_LIVE_DIR=<dossier voktora-live-…> voktora --live`.

Garde-fous de suppression (on ne supprime JAMAIS un dossier arbitraire) : nom `voktora-live-<alphanum>`, dossier réel (pas un lien),
fichier marqueur `.voktora-live` à l'intérieur, et situé dans le dossier temporaire du système.
Désactivés en mode live : synchronisation entre PC, mise à jour automatique, moniteur développeur (rien ne doit survivre).
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

ENV = "VOKTORA_LIVE_DIR"
MARKER = ".voktora-live"
_NAME = re.compile(r"voktora-live-[A-Za-z0-9]{4,40}")


def _safe_live_dir(value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    try:
        if path.is_symlink() or not path.is_dir() or not _NAME.fullmatch(path.name) or not (path / MARKER).is_file():
            return None
        roots = {Path(tempfile.gettempdir()).resolve(), Path("/tmp").resolve(), Path("/var/tmp").resolve()}
        extra = os.environ.get("XDG_RUNTIME_DIR")
        if extra:
            roots.add(Path(extra).resolve())
        return path.resolve() if path.resolve().parent in roots else None
    except OSError:
        return None


def live_dir() -> Path | None:
    return _safe_live_dir(os.environ.get(ENV))


def active() -> bool:
    return live_dir() is not None


def prepare_environment() -> None:
    """À appeler TÔT (avant tout accès aux données) : redirige le dossier de données vers le dossier live."""
    live = live_dir()
    if live is None:
        return
    (live / "data").mkdir(exist_ok=True)
    (live / "projects").mkdir(exist_ok=True)
    os.environ["VOKTORA_DATA_DIR"] = str(live / "data")
    os.environ["VOKTORA_NO_NATIVE"] = "1"
    os.environ.setdefault("XDG_CACHE_HOME", str(live / "cache"))
    os.environ.setdefault("XDG_DATA_HOME", str(live / "xdg-data"))


def configure_storage() -> None:
    """Après chargement de la configuration : les nouveaux projets sont créés dans le dossier live."""
    live = live_dir()
    if live is not None:
        import core
        core.set_storage_config(live / "projects")


def cleanup() -> bool:
    """Supprime les données du mode live (idempotent). Renvoie True si quelque chose a été supprimé."""
    live = live_dir()
    if live is None:
        return False
    removed = False
    for child in live.iterdir():
        if child.name in (MARKER, ".pid"):
            continue                                     # le script d'installation retire le reste (code, venv) puis le dossier
        try:
            shutil.rmtree(child) if child.is_dir() and not child.is_symlink() else child.unlink()
            removed = True
        except OSError:
            pass
    return removed


def sweep_stale(root: Path | None = None) -> list[str]:
    """Supprime les dossiers live abandonnés (script tué brutalement) dont le processus n'existe plus."""
    root = root or Path(tempfile.gettempdir())
    swept: list[str] = []
    try:
        candidates = [p for p in root.iterdir() if _NAME.fullmatch(p.name)]
    except OSError:
        return swept
    for path in candidates:
        if path.is_symlink() or not (path / MARKER).is_file():
            continue
        try:
            pid = int((path / ".pid").read_text().strip())
        except (OSError, ValueError):
            pid = 0
        from devmon.core import pid_alive
        if pid and pid_alive(pid):
            continue
        shutil.rmtree(path, ignore_errors=True)
        swept.append(path.name)
    return swept


def confirm_exit_dialog(parent) -> bool:
    """Fenêtre de fermeture : propose d'exporter avant la suppression. True = fermer (et tout supprimer)."""
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle("Mode live — tout va être supprimé")
    box.setText("Fermer Voktora en mode live ?")
    box.setInformativeText("Votre configuration, vos plugins, vos thèmes, le coffre et les projets créés ici seront SUPPRIMÉS. "
                           "Exportez d'abord ce que vous voulez garder.")
    export = box.addButton("Exporter mes projets…", QMessageBox.ActionRole)
    close = box.addButton("Tout supprimer et fermer", QMessageBox.DestructiveRole)
    cancel = box.addButton("Rester", QMessageBox.RejectRole)
    box.setDefaultButton(cancel)
    while True:
        box.exec()
        clicked = box.clickedButton()
        if clicked is export:
            folder = QFileDialog.getExistingDirectory(parent, "Dossier de destination de l'export")
            if folder:
                try:
                    _export_all(Path(folder))
                    QMessageBox.information(parent, "Export", f"Export enregistré dans {folder}.")
                except Exception as exc:  # noqa: BLE001
                    QMessageBox.warning(parent, "Export", f"Export impossible : {exc}")
            continue
        return clicked is close


def _export_all(dest: Path) -> None:
    import core
    produced = Path(core.export_all_to_zip())
    shutil.move(str(produced), str(dest / produced.name))


def apply_restrictions_note() -> str:
    return "Mode live : synchronisation, mises à jour et moniteur développeur sont désactivés ; tout est supprimé à la fermeture."


def main_cleanup_on_exit() -> None:
    import atexit
    atexit.register(cleanup)
    if sys.platform != "win32":
        import signal
        for sig in (signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, lambda *_: sys.exit(143))
