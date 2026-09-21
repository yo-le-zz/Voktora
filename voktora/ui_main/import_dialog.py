"""
Voktora — ui_main.import_dialog
Import d'un projet existant : archive ZIP ou dossier non compressé.

L'opération elle-même tourne dans un thread avec une fenêtre de progression
(voir task_dialog) : l'interface ne se fige plus pendant le dézippage ou le
déplacement d'un gros dossier.
"""

from __future__ import annotations

from pathlib import Path

import core
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from . import task_dialog, workers

SOURCE_ZIP = "zip"
SOURCE_FOLDER = "folder"

_MODE_LABELS = {
    core.IMPORT_MOVE: "📦  Déplacer le dossier dans Voktora (recommandé)",
    core.IMPORT_COPY: "📄  Copier (le dossier d'origine reste en place)",
    core.IMPORT_LINK: "🔗  Ajouter sur place (rien n'est déplacé)",
}


def classify_path(raw: str) -> str | None:
    """Type de source d'un chemin déposé/collé : SOURCE_ZIP, SOURCE_FOLDER ou None."""
    if not raw.strip():
        return None   # Path("") vaut "." : sans ce garde-fou, un champ vide passerait pour un dossier
    path = Path(raw)
    if path.is_dir():
        return SOURCE_FOLDER
    if path.is_file() and path.suffix.lower() == ".zip":
        return SOURCE_ZIP
    return None


class ImportDialog(QDialog):
    def __init__(self, drive: str, parent: QWidget | None = None,
                 source_path: str = "", source_kind: str = SOURCE_FOLDER):
        super().__init__(parent)
        self._drive = drive
        self.imported_path: Path | None = None
        self.setWindowTitle("Importer un projet — Voktora")
        self.setMinimumWidth(560)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(10)

        title = QLabel("📥  Importer un projet")
        title.setObjectName("appTitle")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        layout.addWidget(workers._make_sep())

        # ── Source ────────────────────────────────
        kind_row = QHBoxLayout()
        self._rb_folder = QRadioButton("📁  Dossier")
        self._rb_zip = QRadioButton("🗜  Archive ZIP")
        group = QButtonGroup(self)
        group.addButton(self._rb_folder)
        group.addButton(self._rb_zip)
        kind_row.addWidget(self._rb_folder)
        kind_row.addWidget(self._rb_zip)
        kind_row.addStretch()
        layout.addLayout(kind_row)

        src_row = QHBoxLayout()
        self.source_edit = QLineEdit()
        self.source_edit.setPlaceholderText("Chemin du dossier ou de l'archive (ou glissez-le sur la fenêtre)")
        btn_browse = QPushButton("📂")
        btn_browse.setFixedWidth(36)
        btn_browse.clicked.connect(self._browse)
        src_row.addWidget(self.source_edit)
        src_row.addWidget(btn_browse)
        layout.addLayout(src_row)

        self._source_info = QLabel("")
        self._source_info.setStyleSheet("color: #a6adc8; font-size: 12px;")
        self._source_info.setWordWrap(True)
        layout.addWidget(self._source_info)

        # ── Mode (dossiers uniquement) ────────────
        self._mode_box = QWidget()
        mode_layout = QVBoxLayout(self._mode_box)
        mode_layout.setContentsMargins(0, 4, 0, 0)
        mode_layout.setSpacing(4)
        self._mode_buttons: dict[str, QRadioButton] = {}
        mode_group = QButtonGroup(self)
        for mode, label in _MODE_LABELS.items():
            rb = QRadioButton(label)
            mode_group.addButton(rb)
            mode_layout.addWidget(rb)
            self._mode_buttons[mode] = rb
        self._mode_buttons[core.IMPORT_MOVE].setChecked(True)
        layout.addWidget(self._mode_box)

        # ── Nom + catégorie ───────────────────────
        layout.addWidget(QLabel("Nom du projet :"))
        self.name_edit = QLineEdit()
        layout.addWidget(self.name_edit)

        layout.addWidget(QLabel("Catégorie :"))
        self.category_combo = QComboBox()
        self.category_combo.setEditable(True)
        self.category_combo.addItem("")
        for cat in core.list_categories():
            self.category_combo.addItem(cat["name"])
        self.category_combo.lineEdit().setPlaceholderText("Aucune — tapez un nom pour en créer une")
        layout.addWidget(self.category_combo)

        self._preview = QLabel("")
        self._preview.setObjectName("pathLabel")
        self._preview.setWordWrap(True)
        layout.addWidget(self._preview)

        layout.addWidget(workers._make_sep())
        buttons = QHBoxLayout()
        btn_cancel = QPushButton("Annuler")
        btn_cancel.clicked.connect(self.reject)
        self._btn_ok = QPushButton("📥  Importer")
        self._btn_ok.setObjectName("primary")
        self._btn_ok.clicked.connect(self._start_import)
        buttons.addWidget(btn_cancel)
        buttons.addWidget(self._btn_ok)
        layout.addLayout(buttons)

        self._rb_folder.toggled.connect(self._on_kind_changed)
        self.source_edit.textChanged.connect(self._on_source_changed)
        self.name_edit.textChanged.connect(self._refresh_preview)
        for rb in self._mode_buttons.values():
            rb.toggled.connect(self._refresh_preview)   # après création de tous les champs

        (self._rb_zip if source_kind == SOURCE_ZIP else self._rb_folder).setChecked(True)
        self._on_kind_changed()
        if source_path:
            self.source_edit.setText(source_path)

    # ── état ─────────────────────────────────────

    def kind(self) -> str:
        return SOURCE_FOLDER if self._rb_folder.isChecked() else SOURCE_ZIP

    def mode(self) -> str:
        for mode, rb in self._mode_buttons.items():
            if rb.isChecked():
                return mode
        return core.IMPORT_MOVE

    def _category_name(self) -> str | None:
        return self.category_combo.currentText().strip() or None

    def _on_kind_changed(self) -> None:
        self._mode_box.setVisible(self.kind() == SOURCE_FOLDER)
        self._on_source_changed()

    def _on_source_changed(self) -> None:
        raw = self.source_edit.text().strip()
        self._source_info.setText("")
        if raw:
            detected = classify_path(raw)
            if detected and detected != self.kind():
                # Le chemin saisi/déposé décide du type : évite une erreur évidente.
                (self._rb_folder if detected == SOURCE_FOLDER else self._rb_zip).setChecked(True)
                return
            if self.kind() == SOURCE_ZIP and detected == SOURCE_ZIP:
                self._describe_zip(Path(raw))
            elif self.kind() == SOURCE_FOLDER and detected == SOURCE_FOLDER:
                self._source_info.setText("Dossier détecté.")
        suggested = self._suggest_name(raw)
        if suggested and not self.name_edit.isModified():
            self.name_edit.blockSignals(True)
            self.name_edit.setText(suggested)
            self.name_edit.blockSignals(False)
        self._refresh_preview()

    def _suggest_name(self, raw: str) -> str:
        if not raw:
            return ""
        if self.kind() == SOURCE_ZIP:
            try:
                return core.inspect_zip(Path(raw)).suggested_name
            except core.ArchiveError:
                return Path(raw).stem
        return Path(raw).name

    def _describe_zip(self, path: Path) -> None:
        try:
            info = core.inspect_zip(path)
        except core.ArchiveError as exc:
            self._source_info.setText(f"⚠  {exc}")
            return
        text = f"{info.file_count} fichier(s), {task_dialog.format_bytes(info.total_bytes)} une fois extrait."
        if info.skipped_links:
            text += f" {info.skipped_links} lien(s) symbolique(s) seront ignorés."
        self._source_info.setText(text)

    def _target_path(self) -> Path | None:
        name = self.name_edit.text().strip()
        if not name:
            return None
        if self.kind() == SOURCE_FOLDER and self.mode() == core.IMPORT_LINK:
            raw = self.source_edit.text().strip()
            return Path(raw) if raw else None
        return core.get_projects_root(self._drive) / name

    def _refresh_preview(self) -> None:
        target = self._target_path()
        if target is None:
            self._preview.setText("")
            return
        text = f"Emplacement : {target}"
        linking = self.kind() == SOURCE_FOLDER and self.mode() == core.IMPORT_LINK
        if not linking and target.exists():
            text += "\n⚠  Ce nom est déjà utilisé : choisissez-en un autre."
        self._preview.setText(text)

    def _browse(self) -> None:
        if self.kind() == SOURCE_ZIP:
            path, _ = QFileDialog.getOpenFileName(self, "Choisir une archive ZIP", "", "Archives ZIP (*.zip)")
        else:
            path = QFileDialog.getExistingDirectory(self, "Choisir le dossier du projet")
        if path:
            self.name_edit.setModified(False)
            self.source_edit.setText(path)

    # ── import ───────────────────────────────────

    def _start_import(self) -> None:
        raw = self.source_edit.text().strip()
        name = self.name_edit.text().strip()
        if not raw or classify_path(raw) != self.kind():
            QMessageBox.warning(self, "Voktora", "Sélectionnez un dossier ou une archive ZIP valide.")
            return
        try:
            core.validate_name(name)
        except ValueError as exc:
            QMessageBox.warning(self, "Voktora — Nom invalide", str(exc))
            return

        if self.kind() == SOURCE_FOLDER and self.mode() == core.IMPORT_MOVE:
            answer = QMessageBox.question(
                self, "Voktora — Déplacer le dossier",
                f"Le dossier « {Path(raw).name} » va être DÉPLACÉ vers :\n"
                f"{core.get_projects_root(self._drive)}\n\n"
                "Il n'existera plus à son emplacement d'origine. Continuer ?",
            )
            if answer != QMessageBox.Yes:
                return

        source, drive, category, mode = Path(raw), self._drive, self._category_name(), self.mode()
        if self.kind() == SOURCE_ZIP:
            def job(ctx):
                return core.import_from_zip(source, drive, name=name, category=category,
                                            on_progress=ctx.progress, cancel=ctx.is_cancelled)
            title = "Extraction de l'archive"
        else:
            def job(ctx):
                return core.import_from_folder(source, drive, mode=mode, name=name, category=category,
                                               on_progress=ctx.progress, cancel=ctx.is_cancelled)
            title = {core.IMPORT_MOVE: "Déplacement du dossier", core.IMPORT_COPY: "Copie du dossier",
                     core.IMPORT_LINK: "Ajout du dossier"}[mode]

        done = task_dialog.run_task(self, title, job, headline=f"{title} — {name}")
        if done.outcome == task_dialog.OUTCOME_OK:
            self.imported_path = done.result
            self.accept()
        elif done.outcome == task_dialog.OUTCOME_ERROR:
            QMessageBox.critical(self, "Voktora — Import impossible", done.error)
        # Annulé : on reste dans la fenêtre d'import, rien n'a été modifié.
