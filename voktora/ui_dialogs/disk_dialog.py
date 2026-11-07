"""
Voktora — ui_dialogs.disk_dialog
Espace disque de chaque projet, avec ce qui est régénérable (caches, compilation, dépendances), nettoyage par
projet et « tout réinitialiser » (double confirmation au-delà du seuil réglé dans Paramètres).
"""

from __future__ import annotations

from pathlib import Path

import core
import diskusage as du
import icons
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

CONFIRM_WORD = "RÉINITIALISER"


class CategoryChoiceDialog(QDialog):
    """Choix des catégories à supprimer."""

    def __init__(self, parent, title: str, intro: str, usages: list[du.ProjectUsage]):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(460)
        self._usages = usages
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        label = QLabel(intro)
        label.setWordWrap(True)
        root.addWidget(label)
        self._boxes: dict[str, QCheckBox] = {}
        for category in du.REGENERABLE:
            size = sum(u.reclaimable_for([category]) for u in usages)
            box = QCheckBox(f"{du.LABELS[category]} — {du.human(size)}")
            box.setChecked(category in du.DEFAULT_RESET)
            box.setEnabled(size > 0)
            box.toggled.connect(self._update_total)
            self._boxes[category] = box
            root.addWidget(box)
        self._total = QLabel("")
        self._total.setStyleSheet("font-weight:bold;")
        root.addWidget(self._total)
        note = QLabel("Jamais supprimés : vos fichiers, .git, et les dossiers suivis par git. "
                      "Les dépendances se réinstallent (réseau requis).")
        note.setWordWrap(True)
        note.setStyleSheet("color:#6c7086; font-size:11px;")
        root.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Continuer")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._update_total()

    def categories(self) -> list[str]:
        return [c for c, box in self._boxes.items() if box.isChecked() and box.isEnabled()]

    def total_bytes(self) -> int:
        return sum(u.reclaimable_for(self.categories()) for u in self._usages)

    def _update_total(self) -> None:
        self._total.setText(f"À libérer : {du.human(self.total_bytes())}")


class DiskUsageDialog(QDialog):
    def __init__(self, parent=None, paths: list[Path] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Espace disque des projets")
        self.setMinimumSize(900, 580)
        self._paths = paths
        self._usages: list[du.ProjectUsage] = []

        self._summary = QLabel("")
        self._summary.setWordWrap(True)
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Projet", "Total", "Régénérable", "Dépendances", "Compilation", "Caches",
                                    ".git", "Snapshots"])
        self._tree.setRootIsDecorated(False)
        self._tree.setSortingEnabled(True)
        self._tree.setColumnWidth(0, 220)
        self._tree.currentItemChanged.connect(self._show_items)
        self._items = QTreeWidget()
        self._items.setHeaderLabels(["Dossier", "Type", "Taille", "Pourquoi"])
        self._items.setRootIsDecorated(False)
        self._items.setColumnWidth(0, 260)
        split = QSplitter(Qt.Vertical)
        split.addWidget(self._tree)
        split.addWidget(self._items)
        split.setSizes([300, 180])

        self._btn_scan = self._btn("Analyser", self.scan, "mdi:magnify-scan")
        self._btn_clean = self._btn("Nettoyer ce projet…", self._clean_selected, "mdi:broom")
        self._btn_reset = self._btn("Tout réinitialiser…", self._reset_all, "mdi:restore-alert")
        self._btn_reset.setObjectName("danger")
        close = QPushButton("Fermer")
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        for b in (self._btn_scan, self._btn_clean, self._btn_reset):
            row.addWidget(b)
        row.addStretch()
        row.addWidget(close)

        self._threshold = QLabel("")
        self._threshold.setStyleSheet("color:#6c7086; font-size:11px;")
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.addWidget(self._summary)
        root.addWidget(split, 1)
        root.addWidget(self._threshold)
        root.addLayout(row)
        self._sync()

    def _btn(self, label: str, slot, icon: str) -> QPushButton:
        b = QPushButton(" " + label)
        b.setIcon(icons.icon(icon))
        b.clicked.connect(slot)
        return b

    # ── Analyse ──────────────────────────────────────────────────────────────

    def project_paths(self) -> list[Path]:
        if self._paths is not None:
            return list(self._paths)
        return [Path(p["path"]) for p in core.list_projects() if isinstance(p, dict) and p.get("path")]

    def _run(self, title: str, job):
        from ui_main import task_dialog
        return task_dialog.run_task(self, title, job, headline=title, unit="items"), task_dialog

    def scan(self) -> None:
        paths = self.project_paths()
        snaps = core.get_data_dir() / "snapshots"
        done, td = self._run("Analyse de l'espace disque", lambda ctx: du.scan_many(
            paths, on_progress=ctx.progress, cancel=ctx.is_cancelled, snapshots_root=snaps))
        if done.outcome == td.OUTCOME_OK:
            self._usages = done.result
            self._fill()
        elif done.outcome == td.OUTCOME_ERROR:
            QMessageBox.critical(self, "Erreur", done.error)

    def _fill(self) -> None:
        self._tree.setSortingEnabled(False)
        self._tree.clear()
        for usage in sorted(self._usages, key=lambda u: -u.total):
            cats = usage.by_category
            item = _SizeItem([usage.path.name, du.human(usage.total), du.human(usage.reclaimable),
                              du.human(cats.get(du.DEPS, 0)), du.human(cats.get(du.BUILD, 0)),
                              du.human(cats.get(du.CACHE, 0)), du.human(cats.get(du.VCS, 0)),
                              du.human(usage.snapshots)])
            item.sizes = [usage.total, usage.reclaimable, cats.get(du.DEPS, 0), cats.get(du.BUILD, 0),
                          cats.get(du.CACHE, 0), cats.get(du.VCS, 0), usage.snapshots]
            item.setData(0, Qt.UserRole, str(usage.path))
            item.setToolTip(0, str(usage.path) + (f"\n{usage.error}" if usage.error else ""))
            if usage.error:
                item.setIcon(0, icons.icon("mdi:alert-circle-outline", color="#f38ba8"))
            self._tree.addTopLevelItem(item)
        self._tree.setSortingEnabled(True)
        if self._tree.topLevelItemCount():
            self._tree.setCurrentItem(self._tree.topLevelItem(0))
        self._sync()

    def _sync(self) -> None:
        total = sum(u.total for u in self._usages)
        reclaim = sum(u.reclaimable for u in self._usages)
        snaps = sum(u.snapshots for u in self._usages)
        if self._usages:
            self._summary.setText(
                f"<b>{len(self._usages)} projet(s)</b> — {du.human(total)} sur le disque. "
                f"<b>{du.human(reclaim)}</b> sont régénérables (caches, compilation, dépendances)"
                + (f" ; {du.human(snaps)} de snapshots." if snaps else "."))
        else:
            self._summary.setText("Cliquez sur <b>Analyser</b> pour mesurer l'espace occupé par chaque projet.")
        self._threshold.setText(f"« Tout réinitialiser » demande une double confirmation au-delà de "
                                f"{du.human(du.confirm_threshold_bytes())} (réglable dans Paramètres → Configuration).")
        self._btn_clean.setEnabled(bool(self._usages))
        self._btn_reset.setEnabled(reclaim > 0)

    def _selected_usage(self) -> du.ProjectUsage | None:
        item = self._tree.currentItem()
        if item is None:
            return None
        path = item.data(0, Qt.UserRole)
        return next((u for u in self._usages if str(u.path) == path), None)

    def _show_items(self, *_args) -> None:
        self._items.clear()
        usage = self._selected_usage()
        if usage is None:
            return
        for entry in usage.items:
            row = QTreeWidgetItem([entry.rel, du.LABELS[entry.category].split(" (")[0], du.human(entry.bytes),
                                   entry.why + (f" — conservé : {entry.protected}" if entry.protected else "")])
            self._items.addTopLevelItem(row)
        self._btn_clean.setEnabled(usage.reclaimable > 0)

    # ── Nettoyage ────────────────────────────────────────────────────────────

    def _clean_selected(self) -> None:
        usage = self._selected_usage()
        if usage is None:
            return
        dlg = CategoryChoiceDialog(self, f"Nettoyer {usage.path.name}",
                                   f"Supprimer les éléments régénérables de « {usage.path.name} » ?", [usage])
        if dlg.exec() != QDialog.Accepted or not dlg.categories():
            return
        self._do_clean([usage], dlg.categories())

    def _do_clean(self, usages: list[du.ProjectUsage], categories: list[str]) -> None:
        done, td = self._run("Nettoyage", lambda ctx: du.reset_all(
            usages, categories, on_progress=ctx.progress, cancel=ctx.is_cancelled))
        if done.outcome == td.OUTCOME_OK:
            freed, notes = done.result
            msg = f"{du.human(freed)} libérés."
            if notes:
                msg += "\n\n" + "\n".join(notes[:8])
            QMessageBox.information(self, "Nettoyage terminé", msg)
            self.scan()
        elif done.outcome == td.OUTCOME_ERROR:
            QMessageBox.critical(self, "Erreur", done.error)

    def confirm_reset(self, total: int, count: int) -> bool:
        """Première confirmation, puis — si `total` dépasse le seuil — une seconde où il faut taper un mot."""
        if QMessageBox.question(
                self, "Tout réinitialiser",
                f"Supprimer {du.human(total)} de caches / compilations / dépendances dans {count} projet(s) ?\n\n"
                "Vos fichiers et votre historique git ne sont pas touchés.") != QMessageBox.Yes:
            return False
        if not du.needs_double_confirmation(total):
            return True
        text, ok = QInputDialog.getText(
            self, "Seconde confirmation",
            f"Cette opération supprime {du.human(total)} (plus que votre seuil de "
            f"{du.human(du.confirm_threshold_bytes())}).\n\nTapez {CONFIRM_WORD} pour confirmer :",
            QLineEdit.Normal, "")
        return bool(ok and text.strip().upper() == CONFIRM_WORD.upper())

    def _reset_all(self) -> None:
        dlg = CategoryChoiceDialog(self, "Tout réinitialiser",
                                   "Supprimer les éléments régénérables de TOUS les projets analysés.", self._usages)
        if dlg.exec() != QDialog.Accepted or not dlg.categories():
            return
        total = dlg.total_bytes()
        if total <= 0:
            QMessageBox.information(self, "Réinitialiser", "Rien à supprimer.")
            return
        if self.confirm_reset(total, sum(1 for u in self._usages if u.reclaimable_for(dlg.categories()))):
            self._do_clean(self._usages, dlg.categories())


class _SizeItem(QTreeWidgetItem):
    """Ligne triable par taille réelle (et non par texte « 12.0 Mo »)."""

    sizes: list[int]

    def __lt__(self, other: QTreeWidgetItem) -> bool:
        column = self.treeWidget().sortColumn()
        if column == 0 or not hasattr(self, "sizes") or not hasattr(other, "sizes"):
            return self.text(column).casefold() < other.text(column).casefold()
        return self.sizes[column - 1] < other.sizes[column - 1]
