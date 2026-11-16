"""Fenêtres 1.1.4 : Archives, Notifications, Raccourcis, Accessibilité, Suggestion de commit (IA)."""

from __future__ import annotations

import threading
from pathlib import Path

import accessibility
import archiving
import core
import notifications
import shortcuts
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class _Result(QObject):
    done = Signal(object, str)                # résultat, erreur


def _background(fn, on_done) -> None:
    box = _Result()
    box.done.connect(on_done)
    _keep.append(box)

    def go() -> None:
        try:
            box.done.emit(fn(), "")
        except Exception as exc:  # noqa: BLE001
            box.done.emit(None, str(exc))
    threading.Thread(target=go, daemon=True).start()


_keep: list = []


# ── Archives ──────────────────────────────────────────────────────────────────────
class ArchivesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Archives de projets")
        self.setMinimumSize(620, 420)
        lay = QVBoxLayout(self)
        hint = QLabel("Archiver crée un ZIP vérifié (intégrité + SHA-256) et retire le projet de la liste. Le dossier d'origine n'est supprimé "
                      "que si vous le demandez, et seulement après relecture de l'archive.")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        row = QHBoxLayout()
        self.pick = QComboBox()
        for e in core.list_projects():
            if e.get("path") and not e.get("archived"):
                self.pick.addItem(e.get("name") or Path(e["path"]).name, e["path"])
        self.remove = QCheckBox("Supprimer ensuite le dossier d'origine")
        btn = QPushButton("Archiver")
        btn.clicked.connect(self._archive)
        row.addWidget(self.pick, 1)
        row.addWidget(self.remove)
        row.addWidget(btn)
        lay.addLayout(row)
        self.list = QListWidget()
        lay.addWidget(self.list, 1)
        row2 = QHBoxLayout()
        restore = QPushButton("Restaurer")
        restore.clicked.connect(self._restore)
        delete = QPushButton("Supprimer l'archive")
        delete.clicked.connect(self._delete)
        row2.addWidget(restore)
        row2.addWidget(delete)
        row2.addStretch()
        lay.addLayout(row2)
        self.status = QLabel("")
        lay.addWidget(self.status)
        self._fill()

    def _fill(self) -> None:
        self.list.clear()
        for e in archiving.list_archived():
            self.list.addItem(f"{e.get('name') or Path(e['path']).name} — {Path(e.get('archive_path', '')).name}"
                              + ("  (dossier supprimé)" if e.get("archive_folder_removed") else ""))
            self.list.item(self.list.count() - 1).setData(Qt.UserRole, e["path"])

    def _archive(self) -> None:
        path = self.pick.currentData()
        if not path:
            return
        if self.remove.isChecked() and QMessageBox.question(self, "Supprimer le dossier", "Supprimer le dossier d'origine après archivage ?") != QMessageBox.Yes:
            return
        self.status.setText("Archivage en cours…")
        _background(lambda: archiving.archive_project(path, self.remove.isChecked()), self._after)

    def _after(self, _res, error: str) -> None:
        self.status.setText("Erreur : " + error if error else "Terminé.")
        self._fill()

    def _selected(self) -> str:
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item else ""

    def _restore(self) -> None:
        path = self._selected()
        if path:
            self.status.setText("Restauration en cours…")
            _background(lambda: archiving.restore_project(path), self._after)

    def _delete(self) -> None:
        path = self._selected()
        if path and QMessageBox.question(self, "Supprimer l'archive", "Supprimer définitivement le ZIP d'archive ?") == QMessageBox.Yes:
            archiving.delete_archive(path)
            self._fill()


# ── Notifications ─────────────────────────────────────────────────────────────────
class NotificationsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Notifications")
        self.setMinimumWidth(480)
        s = notifications.settings()
        lay = QVBoxLayout(self)
        self.enabled = QCheckBox("Activer les notifications de bureau")
        self.enabled.setChecked(bool(s["enabled"]))
        lay.addWidget(self.enabled)
        self.kinds = {}
        for key, label in notifications.KINDS.items():
            box = QCheckBox(label)
            box.setChecked(key in s["kinds"])
            self.kinds[key] = box
            lay.addWidget(box)
        form = QFormLayout()
        self.q1, self.q2 = QLineEdit(s["quiet_start"]), QLineEdit(s["quiet_end"])
        self.q1.setPlaceholderText("22:00")
        self.q2.setPlaceholderText("07:00")
        form.addRow("Ne pas déranger de (HH:MM)", self.q1)
        form.addRow("jusqu'à (HH:MM)", self.q2)
        lay.addLayout(form)
        lay.addWidget(QLabel("Historique récent :"))
        self.history = QListWidget()
        for n in reversed(list(notifications.HISTORY)):
            self.history.addItem(f"{'🔔' if n.shown else '·'} {n.title} {n.body}".strip())
        lay.addWidget(self.history)
        test = QPushButton("Envoyer une notification de test")
        test.clicked.connect(lambda: notifications.notify("task", "Voktora", "Notification de test", dedupe_seconds=0))
        lay.addWidget(test)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Close)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _save(self) -> None:
        notifications.save_settings({"enabled": self.enabled.isChecked(), "kinds": [k for k, b in self.kinds.items() if b.isChecked()],
                                     "quiet_start": self.q1.text().strip(), "quiet_end": self.q2.text().strip()})
        self.accept()


# ── Raccourcis ────────────────────────────────────────────────────────────────────
class ShortcutsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Raccourcis clavier")
        self.setMinimumSize(520, 400)
        lay = QVBoxLayout(self)
        self.table = QTableWidget(len(shortcuts.DEFAULTS), 2)
        self.table.setHorizontalHeaderLabels(["Action", "Raccourci"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 280)
        self.edits: dict[str, QKeySequenceEdit] = {}
        eff = shortcuts.effective()
        for row, (ident, (label, _default)) in enumerate(shortcuts.DEFAULTS.items()):
            self.table.setItem(row, 0, QTableWidgetItem(label))
            edit = QKeySequenceEdit()
            from PySide6.QtGui import QKeySequence
            edit.setKeySequence(QKeySequence(eff[ident]))
            self.table.setCellWidget(row, 1, edit)
            self.edits[ident] = edit
        lay.addWidget(self.table)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        row = QHBoxLayout()
        for text, slot in (("Réinitialiser", self._reset), ("Importer…", self._import), ("Exporter…", self._export)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch()
        save = QPushButton("Enregistrer")
        save.clicked.connect(self._save)
        row.addWidget(save)
        lay.addLayout(row)

    def _mapping(self) -> dict[str, str]:
        return {i: e.keySequence().toString() for i, e in self.edits.items()}

    def _save(self) -> None:
        try:
            shortcuts.set_shortcuts(self._mapping())
            self.status.setText("Enregistré et appliqué.")
        except shortcuts.ShortcutError as exc:
            self.status.setText(str(exc))

    def _reset(self) -> None:
        from PySide6.QtGui import QKeySequence
        for ident, edit in self.edits.items():
            edit.setKeySequence(QKeySequence(shortcuts.DEFAULTS[ident][1]))

    def _export(self) -> None:
        name, _ = QFileDialog.getSaveFileName(self, "Exporter les raccourcis", "voktora-raccourcis.json", "JSON (*.json)")
        if name:
            Path(name).write_text(shortcuts.export_text(), encoding="utf-8")

    def _import(self) -> None:
        name, _ = QFileDialog.getOpenFileName(self, "Importer des raccourcis", "", "JSON (*.json)")
        if not name:
            return
        try:
            merged = shortcuts.import_text(Path(name).read_text(encoding="utf-8"))
        except (shortcuts.ShortcutError, OSError) as exc:
            self.status.setText("Import refusé : " + str(exc))
            return
        from PySide6.QtGui import QKeySequence
        for ident, edit in self.edits.items():
            edit.setKeySequence(QKeySequence(merged[ident]))
        self.status.setText("Importé et appliqué.")


# ── Accessibilité ─────────────────────────────────────────────────────────────────
class AccessibilityDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Accessibilité")
        self.setMinimumWidth(440)
        s = accessibility.settings()
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.scale = QDoubleSpinBox()
        self.scale.setRange(accessibility.SCALE_MIN, accessibility.SCALE_MAX)
        self.scale.setSingleStep(0.1)
        self.scale.setValue(s["font_scale"])
        form.addRow("Taille du texte (×)", self.scale)
        lay.addLayout(form)
        self.contrast = QCheckBox("Contraste renforcé (bordures et sélection très visibles)")
        self.contrast.setChecked(s["high_contrast"])
        self.focus = QCheckBox("Cadre de focus épais (navigation au clavier)")
        self.focus.setChecked(s["strong_focus"])
        self.motion = QCheckBox("Réduire les animations")
        self.motion.setChecked(s["reduce_motion"])
        for w in (self.contrast, self.focus, self.motion):
            lay.addWidget(w)
        self.report = QLabel("")
        self.report.setWordWrap(True)
        lay.addWidget(self.report)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Close)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        win = parent.window() if parent else None
        if win is not None:
            missing = accessibility.audit(win)
            self.report.setText(f"Audit : {len(missing)} bouton(s) sans nom accessible." if missing else "Audit : tous les boutons ont un nom accessible.")

    def _save(self) -> None:
        accessibility.save_settings({"font_scale": self.scale.value(), "high_contrast": self.contrast.isChecked(),
                                     "strong_focus": self.focus.isChecked(), "reduce_motion": self.motion.isChecked()})
        import theme_manager
        app = QGuiApplication.instance()
        accessibility.apply_font(app)
        theme_manager.apply_theme_to_app(app)
        self.accept()


# ── Suggestion de message de commit (IA) ──────────────────────────────────────────
class AICommitDialog(QDialog):
    def __init__(self, parent=None, project: Path | None = None):
        super().__init__(parent)
        self.setWindowTitle("Suggestion de message de commit (IA)")
        self.setMinimumSize(560, 420)
        self.project = project
        lay = QVBoxLayout(self)
        self.info = QLabel(f"Projet : {project}" if project else "Sélectionnez d'abord un projet.")
        lay.addWidget(self.info)
        self.warn = QLabel("")
        self.warn.setWordWrap(True)
        lay.addWidget(self.warn)
        self.out = QPlainTextEdit()
        lay.addWidget(self.out, 1)
        row = QHBoxLayout()
        self.go = QPushButton("Proposer un message")
        self.explain = QPushButton("Expliquer le diff")
        self.copy = QPushButton("Copier")
        self.go.clicked.connect(self._suggest)
        self.explain.clicked.connect(self._explain)
        self.copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.out.toPlainText()))
        for b in (self.go, self.explain, self.copy):
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        note = QLabel("Voktora ne commit ni ne pousse jamais : il propose seulement un texte à copier. "
                      "Le diff (borné, secrets masqués, fichiers sensibles ignorés) est envoyé au fournisseur IA actif.")
        note.setWordWrap(True)
        lay.addWidget(note)
        import ai_git
        self._ai = ai_git
        self.provider = core.get_active_ai_provider()
        if not self.provider:
            self.warn.setText("Aucun fournisseur IA actif : configurez-en un dans l'assistant IA.")
            self.go.setEnabled(self.explain.isEnabled() and False)
        elif not ai_git.provider_is_local(self.provider):
            self.warn.setText("⚠ Ce fournisseur n'est pas local : le diff sera envoyé hors de votre machine.")
        if not project:
            self.go.setEnabled(False)
            self.explain.setEnabled(False)

    def _run(self, fn) -> None:
        self.out.setPlainText("Réflexion en cours…")
        _background(fn, lambda res, err: self.out.setPlainText("Erreur : " + err if err else res))

    def _suggest(self) -> None:
        def work():
            r = self._ai.suggest_commit(self.provider, self.project)
            text = r["subject"] + ("\n\n" + r["body"] if r["body"] else "")
            notes = []
            if r["too_long"]:
                notes.append("titre > 72 caractères")
            if not r["conventional"]:
                notes.append("pas au format Conventional Commits")
            if r["skipped"]:
                notes.append("fichiers ignorés : " + ", ".join(r["skipped"][:5]))
            return text + ("\n\n— " + " ; ".join(notes) if notes else "")
        self._run(work)

    def _explain(self) -> None:
        self._run(lambda: self._ai.explain_diff(self.provider, self.project))
