"""
Voktora — ui_dialogs.snapshot_dialog
Fragment de ui_dialogs.py extrait lors du découpage v1.0.2 en package.
"""

from __future__ import annotations

from pathlib import Path

import snapshots
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

# ════════════════════════════════════════════════════════════════════════════
# SNAPSHOTS UI
# ════════════════════════════════════════════════════════════════════════════

class SnapshotDialog(QDialog):
    """Creation, liste et restauration de snapshots d'un projet."""

    def __init__(self, project_path: Path, parent=None):
        super().__init__(parent)
        self._path = project_path
        self.setWindowTitle(f"Snapshots — {project_path.name}")
        self.setMinimumSize(520, 360)

        v = QVBoxLayout(self)
        v.setSpacing(10)
        v.setContentsMargins(14, 12, 14, 12)
        v.addWidget(QLabel(f"<b>Snapshots</b> — {project_path.name}",
                           styleSheet="color:#cdd6f4;"))

        self._list = QListWidget()
        v.addWidget(self._list)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        v.addWidget(self._progress)

        row = QHBoxLayout()
        for label, slot in [
            ("Creer", self._create),
            ("Restaurer", self._restore),
            ("Comparer", self._diff),
            ("Supprimer", self._delete),
        ]:
            b = QPushButton(label)
            if label == "Creer":
                b.setObjectName("primary")
            b.clicked.connect(slot)
            row.addWidget(b)
        btn_close = QPushButton("Fermer")
        btn_close.clicked.connect(self.accept)
        row.addStretch()
        row.addWidget(btn_close)
        v.addLayout(row)

        self._refresh()

    def _refresh(self) -> None:
        self._list.clear()
        for s in snapshots.list_snaps(self._path):
            item = QListWidgetItem(f"{s.label}  /  {s.timestamp}  /  {s.size_mb} MB")
            item.setData(Qt.UserRole, str(s.path))
            self._list.addItem(item)

    def _selected_snap(self):
        item = self._list.currentItem()
        return Path(item.data(Qt.UserRole)) if item else None

    def _run(self, title: str, job):
        """Exécute `job(ctx)` dans un thread avec fenêtre de progression (l'interface ne se fige jamais)."""
        from ui_main import task_dialog  # import tardif : évite un cycle ui_main <-> ui_dialogs
        return task_dialog.run_task(self, title, job, headline=title), task_dialog

    def _create(self) -> None:
        label, ok = QInputDialog.getText(self, "Label", "Label du snapshot :")
        if not ok:
            return
        path = self._path
        done, td = self._run(
            "Création du snapshot",
            lambda ctx: snapshots.create(path, label, on_progress=ctx.progress, cancel=ctx.is_cancelled))
        if done.outcome == td.OUTCOME_OK:
            self._refresh()
            QMessageBox.information(self, "Snapshot cree", str(done.result))
        elif done.outcome == td.OUTCOME_ERROR:
            QMessageBox.critical(self, "Erreur", done.error)

    def _restore(self) -> None:
        snap = self._selected_snap()
        if not snap:
            return
        target = QFileDialog.getExistingDirectory(self, "Dossier de restauration")
        if not target:
            return
        dest = Path(target) / self._path.name
        overwrite = False
        if dest.exists():
            if QMessageBox.question(self, "Ecraser ?", f"{dest} existe. Ecraser ?") != QMessageBox.Yes:
                return
            overwrite = True
        done, td = self._run(
            "Restauration du snapshot",
            lambda ctx: snapshots.restore(snap, dest, overwrite=overwrite,
                                          on_progress=ctx.progress, cancel=ctx.is_cancelled))
        if done.outcome == td.OUTCOME_OK:
            QMessageBox.information(self, "Restaure", str(dest))
        elif done.outcome == td.OUTCOME_ERROR:
            QMessageBox.critical(self, "Erreur", done.error)

    def _diff(self) -> None:
        snaps_list = snapshots.list_snaps(self._path)
        if len(snaps_list) < 2:
            QMessageBox.information(self, "Diff", "Besoin d'au moins 2 snapshots.")
            return
        names = [s.label for s in snaps_list]
        a_name, ok = QInputDialog.getItem(self, "Snapshot A", "Choisir A :", names, 0, False)
        if not ok:
            return
        b_name, ok = QInputDialog.getItem(self, "Snapshot B", "Choisir B :", names, 1, False)
        if not ok:
            return
        snap_a = next(s for s in snaps_list if s.label == a_name)
        snap_b = next(s for s in snaps_list if s.label == b_name)
        done, td = self._run("Comparaison des snapshots",
                             lambda ctx: snapshots.diff_snaps(snap_a.path, snap_b.path))
        if done.outcome != td.OUTCOME_OK:
            if done.outcome == td.OUTCOME_ERROR:
                QMessageBox.critical(self, "Erreur", done.error)
            return
        diff   = done.result
        text   = "\n".join(f"{v.upper():10}  {k}" for k, v in sorted(diff.items()))
        dlg    = QDialog(self)
        dlg.setWindowTitle("Diff snapshots")
        dlg.setMinimumSize(500, 380)
        lay    = QVBoxLayout(dlg)
        te     = QTextEdit()
        te.setReadOnly(True)
        te.setPlainText(text or "Aucune difference.")
        te.setStyleSheet("font-family:Consolas,'DejaVu Sans Mono',monospace; font-size:12px;")
        lay.addWidget(te)
        close  = QPushButton("Fermer")
        close.clicked.connect(dlg.accept)
        lay.addWidget(close)
        dlg.exec()

    def _delete(self) -> None:
        snap = self._selected_snap()
        if not snap:
            return
        if QMessageBox.question(self, "Supprimer", "Supprimer ce snapshot ?") == QMessageBox.Yes:
            snapshots.delete_snap(snap)
            self._refresh()


