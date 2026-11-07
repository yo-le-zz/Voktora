"""
Voktora — ui_dialogs.snapshot_dialog
Sauvegardes complètes d'un projet : créer, restaurer (sur place / ailleurs / fichiers choisis), comparer
(deux snapshots ou snapshot ↔ état actuel, avec diff texte), vérifier l'intégrité, nettoyer.
Toutes les opérations longues passent par une fenêtre de progression annulable.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import core
import icons
import snapshots
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

STATUS_LABEL = {"added": "Ajouté", "removed": "Supprimé", "modified": "Modifié", "renamed": "Renommé"}
STATUS_ICON = {"added": ("mdi:plus-circle-outline", "#a6e3a1"), "removed": ("mdi:minus-circle-outline", "#f38ba8"),
               "modified": ("mdi:pencil-circle-outline", "#f9e2af"), "renamed": ("mdi:swap-horizontal", "#89b4fa")}


def _size(n: int) -> str:
    from diskusage import human
    return human(n)


def _when(timestamp: str) -> str:
    try:
        return datetime.strptime(timestamp, "%Y%m%d_%H%M%S").strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return timestamp or "—"


class SnapshotCreateDialog(QDialog):
    """Options d'une nouvelle sauvegarde."""

    def __init__(self, parent=None, default_label: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Nouveau snapshot")
        self.setMinimumWidth(440)
        self.label = QLineEdit(default_label)
        self.label.setPlaceholderText("ex. avant refactor (optionnel)")
        self.note = QPlainTextEdit()
        self.note.setPlaceholderText("Note (optionnelle)")
        self.note.setFixedHeight(70)
        self.include_git = QCheckBox("Inclure l'historique git (.git) — recommandé pour une sauvegarde complète")
        self.include_git.setChecked(True)
        self.include_all = QCheckBox("Inclure aussi dépendances, caches et compilations (node_modules, target…)")
        form = QFormLayout()
        form.addRow("Nom :", self.label)
        form.addRow("Note :", self.note)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.addLayout(form)
        root.addWidget(self.include_git)
        root.addWidget(self.include_all)
        hint = QLabel("Par défaut les dossiers régénérables sont exclus : ils sont listés dans le snapshot "
                      "et reviennent avec un build / une installation.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#6c7086; font-size:11px;")
        root.addWidget(hint)
        root.addWidget(buttons)


class ComparisonDialog(QDialog):
    """Résultat d'une comparaison : liste filtrable + diff du fichier sélectionné."""

    def __init__(self, comparison: snapshots.Comparison, title: str, snap_a: Path, snap_b: Path | None,
                 project: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(780, 520)
        self._cmp, self._a, self._b, self._project = comparison, snap_a, snap_b, project

        summary = QLabel(comparison.summary() + (f"   —   variation : {'+' if comparison.bytes_delta >= 0 else '-'}"
                                                 f"{_size(abs(comparison.bytes_delta))}" if comparison.changes else ""))
        summary.setWordWrap(True)
        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Filtrer par nom ou statut (ajouté, modifié…)")
        self._filter.textChanged.connect(self._fill)
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Fichier", "Statut", "Avant", "Après"])
        self._tree.setRootIsDecorated(False)
        self._tree.setColumnWidth(0, 300)
        self._tree.currentItemChanged.connect(self._show_diff)
        self._diff = QTextEdit()
        self._diff.setReadOnly(True)
        self._diff.setStyleSheet("font-family:Consolas,'DejaVu Sans Mono',monospace; font-size:12px;")
        self._diff.setPlaceholderText("Sélectionnez un fichier pour voir les différences.")

        split = QSplitter(Qt.Vertical)
        split.addWidget(self._tree)
        split.addWidget(self._diff)
        split.setSizes([240, 240])
        close = QPushButton("Fermer")
        close.clicked.connect(self.accept)
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.addWidget(summary)
        root.addWidget(self._filter)
        root.addWidget(split, 1)
        root.addWidget(close, 0, Qt.AlignRight)
        self._fill()

    def _fill(self) -> None:
        needle = self._filter.text().strip().casefold()
        self._tree.clear()
        for change in self._cmp.changes:
            label = STATUS_LABEL[change.status]
            if needle and needle not in change.path.casefold() and needle not in label.casefold():
                continue
            name = f"{change.old_path}  →  {change.path}" if change.status == "renamed" else change.path
            item = QTreeWidgetItem([name, label, _size(change.size_a) if change.size_a else "",
                                    _size(change.size_b) if change.size_b else ""])
            icon_id, color = STATUS_ICON[change.status]
            item.setIcon(0, icons.icon(icon_id, color=color))
            item.setData(0, Qt.UserRole, change)
            self._tree.addTopLevelItem(item)
        if self._tree.topLevelItemCount():
            self._tree.setCurrentItem(self._tree.topLevelItem(0))
        else:
            self._diff.setPlainText("")

    def _show_diff(self, current, _previous) -> None:
        if current is None:
            return
        change: snapshots.FileChange = current.data(0, Qt.UserRole)
        if change.status == "added" and self._b is None:
            text = snapshots.file_diff(self._a, change.path, None, self._project)
        elif change.status == "removed":
            text = "(fichier absent de l'autre version)"
        else:
            text = snapshots.file_diff(self._a, change.path, self._b, self._project, old_path_of(change))
        self._diff.setPlainText(text)


def old_path_of(change: snapshots.FileChange) -> str:
    return change.old_path if change.status == "renamed" else ""


class SnapshotDialog(QDialog):
    """Création, liste, restauration, comparaison et vérification des snapshots d'un projet."""

    def __init__(self, project_path: Path, parent=None):
        super().__init__(parent)
        self._path = Path(project_path)
        self.setWindowTitle(f"Snapshots — {self._path.name}")
        self.setMinimumSize(820, 520)

        v = QVBoxLayout(self)
        v.setSpacing(10)
        v.setContentsMargins(14, 12, 14, 12)
        v.addWidget(QLabel(f"<b>Sauvegardes complètes</b> — {self._path.name}"))

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Version", "Date", "Taille", "Fichiers", "Git", "Type"])
        self._tree.setRootIsDecorated(False)
        self._tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._tree.setColumnWidth(0, 220)
        self._tree.itemSelectionChanged.connect(self._on_select)
        self._details = QTextEdit()
        self._details.setReadOnly(True)
        self._details.setMaximumHeight(120)
        split = QSplitter(Qt.Vertical)
        split.addWidget(self._tree)
        split.addWidget(self._details)
        split.setSizes([300, 110])
        v.addWidget(split, 1)

        self._status = QLabel("")
        self._status.setStyleSheet("color:#a6adc8;")
        v.addWidget(self._status)

        row = QHBoxLayout()
        self._btn_create = self._button("Créer…", self._create, "mdi:content-save-plus-outline", "primary")
        self._btn_restore = self._button("Restaurer", None, "mdi:backup-restore")
        menu = QMenu(self._btn_restore)
        menu.addAction("Sur place (sauvegarde de sécurité automatique)", self._restore_in_place)
        menu.addAction("Dans un autre dossier…", self._restore_elsewhere)
        menu.addAction("Seulement certains fichiers…", self._restore_files)
        self._btn_restore.setMenu(menu)
        self._btn_compare = self._button("Comparer", None, "mdi:compare")
        cmenu = QMenu(self._btn_compare)
        cmenu.addAction("Avec l'état actuel du projet", self._compare_current)
        cmenu.addAction("Avec le snapshot précédent", self._compare_previous)
        cmenu.addAction("Avec un autre snapshot…", self._compare_other)
        self._btn_compare.setMenu(cmenu)
        self._btn_verify = self._button("Vérifier", self._verify, "mdi:shield-check-outline")
        self._btn_delete = self._button("Supprimer", self._delete, "mdi:delete-outline")
        self._btn_prune = self._button("Nettoyer…", self._prune, "mdi:broom")
        for b in (self._btn_create, self._btn_restore, self._btn_compare, self._btn_verify, self._btn_delete,
                  self._btn_prune):
            row.addWidget(b)
        close = QPushButton("Fermer")
        close.clicked.connect(self.accept)
        row.addStretch()
        row.addWidget(close)
        v.addLayout(row)
        self._refresh()

    def _button(self, label: str, slot, icon: str = "", name: str = "") -> QPushButton:
        b = QPushButton(" " + label)
        if icon:
            b.setIcon(icons.icon(icon))
        if name:
            b.setObjectName(name)
        if slot is not None:
            b.clicked.connect(slot)
        return b

    # ── Liste ────────────────────────────────────────────────────────────────

    def _refresh(self) -> None:
        self._tree.clear()
        snaps = snapshots.list_snaps(self._path)
        for s in snaps:
            git = f"{s.git_branch} @ {s.git_commit[:7]}" if s.git_commit else (s.git_branch or "—")
            kind = {"auto": "Auto", "pre-restore": "Sécurité"}.get(s.kind, "Manuel")
            item = QTreeWidgetItem([s.title, _when(s.timestamp), f"{s.size_mb} Mo",
                                    str(s.files) if s.files else "—", git, kind])
            item.setData(0, Qt.UserRole, str(s.path))
            item.setIcon(0, icons.icon("mdi:history" if s.kind != "pre-restore" else "mdi:shield-outline"))
            self._tree.addTopLevelItem(item)
        if snaps:
            self._tree.setCurrentItem(self._tree.topLevelItem(0))
        self._status.setText(f"{len(snaps)} snapshot(s) — {sum(s.size_mb for s in snaps):.1f} Mo au total")
        self._on_select()

    def _selected(self) -> list[Path]:
        return [Path(i.data(0, Qt.UserRole)) for i in self._tree.selectedItems()]

    def _selected_snap(self) -> Path | None:
        sel = self._selected()
        return sel[0] if sel else None

    def _info(self, path: Path) -> snapshots.SnapInfo | None:
        return next((s for s in snapshots.list_snaps(self._path) if s.path == path), None)

    def _on_select(self) -> None:
        sel = self._selected()
        for b in (self._btn_restore, self._btn_verify, self._btn_delete):
            b.setEnabled(bool(sel))
        self._btn_compare.setEnabled(len(sel) >= 1)
        if len(sel) == 2:
            self._details.setHtml("<p>Deux snapshots sélectionnés : <b>Comparer → Avec un autre snapshot</b> "
                                  "les compare directement.</p>")
            return
        if not sel:
            self._details.setHtml("<p>Aucun snapshot. Cliquez sur <b>Créer…</b>.</p>")
            return
        info = self._info(sel[0])
        if info is None:
            return
        lines = [f"<b>{info.title}</b> — {_when(info.timestamp)}"]
        if info.note:
            lines.append(f"<i>{info.note}</i>")
        if info.git_commit:
            lines.append(f"Git : {info.git_branch} @ <code>{info.git_commit[:12]}</code>")
        lines.append("Contenu : " + ("historique git inclus" if info.includes_git else "sans historique git")
                     + (", dépendances/caches inclus" if info.includes_regenerable and info.format >= 2 else ""))
        if info.excluded:
            lines.append("Exclus (régénérables) : " + ", ".join(f"{e['path']} ({_size(e.get('bytes', 0))})"
                                                                for e in info.excluded[:8]))
        if info.format < 2:
            lines.append("Ancien format : pas d'empreintes SHA-256 ; vérification limitée au CRC.")
        self._details.setHtml("<br>".join(lines))

    # ── Tâches avec progression ─────────────────────────────────────────────

    def _run(self, title: str, job):
        from ui_main import task_dialog  # import tardif : évite un cycle ui_main <-> ui_dialogs
        return task_dialog.run_task(self, title, job, headline=title), task_dialog

    def _report(self, done, td, success: str = "") -> bool:
        if done.outcome == td.OUTCOME_OK:
            if success:
                self._status.setText(success)
            return True
        if done.outcome == td.OUTCOME_ERROR:
            QMessageBox.critical(self, "Erreur", done.error)
        return False

    # ── Actions ──────────────────────────────────────────────────────────────

    def _create(self) -> None:
        dlg = SnapshotCreateDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        keep = int(core.get_app_config().get("snapshot_keep", 0) or 0)
        path, opts = self._path, (dlg.label.text().strip(), dlg.note.toPlainText().strip(),
                                  dlg.include_git.isChecked(), dlg.include_all.isChecked())
        done, td = self._run("Création du snapshot", lambda ctx: snapshots.create(
            path, opts[0], on_progress=ctx.progress, cancel=ctx.is_cancelled, note=opts[1],
            include_git=opts[2], include_regenerable=opts[3], keep=keep))
        if self._report(done, td, "Snapshot créé."):
            self._refresh()

    def _restore_in_place(self) -> None:
        snap = self._selected_snap()
        if not snap:
            return
        if QMessageBox.question(
                self, "Restaurer sur place",
                f"Remplacer le contenu actuel de « {self._path.name} » par ce snapshot ?\n\n"
                "Un snapshot « Avant restauration » est créé d'abord : vous pourrez revenir en arrière.",
        ) != QMessageBox.Yes:
            return
        path = self._path
        done, td = self._run("Restauration du snapshot", lambda ctx: snapshots.restore_in_place(
            snap, path, safety=True, on_progress=ctx.progress, cancel=ctx.is_cancelled))
        if self._report(done, td, "Projet restauré."):
            self._refresh()

    def _restore_elsewhere(self) -> None:
        snap = self._selected_snap()
        target = QFileDialog.getExistingDirectory(self, "Dossier de restauration") if snap else ""
        if not target:
            return
        dest = Path(target) / self._path.name
        overwrite = False
        if dest.exists():
            if QMessageBox.question(self, "Écraser ?", f"{dest} existe. Écraser ?") != QMessageBox.Yes:
                return
            overwrite = True
        done, td = self._run("Restauration du snapshot", lambda ctx: snapshots.restore(
            snap, dest, overwrite=overwrite, on_progress=ctx.progress, cancel=ctx.is_cancelled))
        if self._report(done, td):
            QMessageBox.information(self, "Restauré", str(dest))

    def _restore_files(self) -> None:
        snap = self._selected_snap()
        if not snap:
            return
        done, td = self._run("Lecture du snapshot", lambda ctx: snapshots.compare(snap, None, self._path))
        if not self._report(done, td):
            return
        names = sorted(c.path if c.status != "renamed" else c.old_path for c in done.result.changes
                       if c.status != "added")
        if not names:
            QMessageBox.information(self, "Restaurer", "Aucun fichier ne diffère de l'état actuel.")
            return
        picker = QDialog(self)
        picker.setWindowTitle("Fichiers à restaurer")
        picker.setMinimumSize(460, 380)
        lst = QListWidget()
        lst.setSelectionMode(QAbstractItemView.MultiSelection)
        for name in names:
            lst.addItem(QListWidgetItem(name))
        lst.selectAll()
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(picker.accept)
        buttons.rejected.connect(picker.reject)
        lay = QVBoxLayout(picker)
        lay.addWidget(QLabel("Fichiers différents de l'état actuel (les versions actuelles seront écrasées) :"))
        lay.addWidget(lst)
        lay.addWidget(buttons)
        if picker.exec() != QDialog.Accepted:
            return
        chosen = [i.text() for i in lst.selectedItems()]
        if not chosen:
            return
        done, td = self._run("Restauration de fichiers", lambda ctx: snapshots.restore_files(
            snap, self._path, chosen, cancel=ctx.is_cancelled))
        if self._report(done, td):
            QMessageBox.information(self, "Restauré", f"{len(done.result)} fichier(s) restauré(s).")

    def _show_comparison(self, title: str, a: Path, b: Path | None) -> None:
        done, td = self._run("Comparaison", lambda ctx: snapshots.compare(a, b, self._path, cancel=ctx.is_cancelled))
        if self._report(done, td):
            ComparisonDialog(done.result, title, a, b, self._path, self).exec()

    def _compare_current(self) -> None:
        snap = self._selected_snap()
        if snap:
            self._show_comparison("Snapshot ↔ état actuel", snap, None)

    def _compare_previous(self) -> None:
        snap = self._selected_snap()
        ordered = [s.path for s in snapshots.list_snaps(self._path)]
        if snap is None or snap not in ordered or ordered.index(snap) + 1 >= len(ordered):
            QMessageBox.information(self, "Comparer", "Pas de snapshot plus ancien.")
            return
        self._show_comparison("Snapshot précédent ↔ sélectionné", ordered[ordered.index(snap) + 1], snap)

    def _compare_other(self) -> None:
        sel = self._selected()
        if len(sel) == 2:
            a, b = sorted(sel, key=lambda p: p.name)
            self._show_comparison("Comparaison de deux snapshots", a, b)
            return
        snaps = [s for s in snapshots.list_snaps(self._path) if s.path not in sel]
        if not sel or not snaps:
            QMessageBox.information(self, "Comparer", "Besoin d'au moins 2 snapshots.")
            return
        names = [s.title for s in snaps]
        choice, ok = QInputDialog.getItem(self, "Comparer", "Comparer avec :", names, 0, False)
        if ok:
            other = snaps[names.index(choice)].path
            a, b = sorted([sel[0], other], key=lambda p: p.name)
            self._show_comparison("Comparaison de deux snapshots", a, b)

    def _verify(self) -> None:
        snap = self._selected_snap()
        if not snap:
            return
        done, td = self._run("Vérification de l'intégrité", lambda ctx: snapshots.verify(
            snap, on_progress=ctx.progress, cancel=ctx.is_cancelled))
        if not self._report(done, td):
            return
        problems = done.result
        if problems:
            QMessageBox.warning(self, "Snapshot altéré", "\n".join(problems[:15]))
        else:
            QMessageBox.information(self, "Intégrité", "Tous les fichiers sont intacts (CRC et SHA-256).")

    def _delete(self) -> None:
        sel = self._selected()
        if not sel:
            return
        if QMessageBox.question(self, "Supprimer", f"Supprimer {len(sel)} snapshot(s) ?") == QMessageBox.Yes:
            for path in sel:
                snapshots.delete_snap(path)
            self._refresh()

    def _prune(self) -> None:
        count, ok = QInputDialog.getInt(self, "Nettoyer", "Garder les N snapshots les plus récents :", 5, 1, 999)
        if not ok:
            return
        victims = max(0, len(snapshots.list_snaps(self._path)) - count)
        if victims == 0:
            QMessageBox.information(self, "Nettoyer", "Rien à supprimer.")
            return
        if QMessageBox.question(self, "Nettoyer", f"Supprimer les {victims} plus ancien(s) snapshot(s) ?") \
                == QMessageBox.Yes:
            snapshots.prune(self._path, count)
            self._refresh()
