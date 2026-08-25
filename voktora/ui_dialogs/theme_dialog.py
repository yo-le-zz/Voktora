"""
Voktora — ui_dialogs.theme_dialog
Fragment de ui_dialogs.py extrait lors du découpage v1.0.2 en package.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import ClassVar

import core
import theme_manager
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


# ════════════ theme_dialog.py ════════════
class CustomThemeDialog(QDialog):
    """Dialogue pour créer ou modifier un thème personnalisé."""

    # Couleurs clés exposées dans l'éditeur (les plus impactantes visuellement)
    _COLOR_KEYS: ClassVar[list[tuple[str, str]]] = [
        ("base",      "Fond principal"),
        ("mantle",    "Fond secondaire / panneaux"),
        ("crust",     "Fond profond / barre de statut"),
        ("surface0",  "Surface 0 (listes, champs)"),
        ("surface1",  "Surface 1 (bordures)"),
        ("surface2",  "Surface 2 (scrollbars)"),
        ("text",      "Texte principal"),
        ("subtext1",  "Texte secondaire"),
        ("overlay0",  "Texte désactivé"),
        ("blue",      "Couleur primaire (accent)"),
        ("lavender",  "Accent 2"),
        ("green",     "Succès / info positive"),
        ("yellow",    "Avertissement"),
        ("red",       "Erreur / danger"),
        ("primary",   "Bouton primary"),
    ]

    def __init__(self, parent=None, theme_data: dict | None = None,
                 theme_name: str = ""):
        super().__init__(parent)
        self._editing = bool(theme_name)
        self._original_name = theme_name

        title = f"✏️ Modifier — {theme_name}" if self._editing else "➕ Nouveau thème"
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumSize(540, 600)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(12)

        # ── Nom ──
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        self.name_edit = QLineEdit(theme_data.get("name", "") if theme_data else "")
        self.name_edit.setPlaceholderText("Nom du thème (ex: Mon Thème)")
        form.addRow("Nom :", self.name_edit)

        self.slug_edit = QLineEdit(theme_name)
        self.slug_edit.setPlaceholderText("slug_sans_espace (identifiant fichier)")
        if self._editing:
            self.slug_edit.setEnabled(False)
        form.addRow("Identifiant :", self.slug_edit)

        self.desc_edit = QLineEdit(theme_data.get("description", "") if theme_data else "")
        self.desc_edit.setPlaceholderText("Description courte du thème")
        form.addRow("Description :", self.desc_edit)
        layout.addLayout(form)

        # ── Copier depuis un thème existant ──
        row_copy = QHBoxLayout()
        lbl_copy = QLabel("Partir de :")
        self.base_combo = QComboBox()
        for t in theme_manager.get_available_themes():
            self.base_combo.addItem(t)
        btn_copy = QPushButton("Copier les couleurs")
        btn_copy.clicked.connect(self._copy_from_base)
        row_copy.addWidget(lbl_copy)
        row_copy.addWidget(self.base_combo, 1)
        row_copy.addWidget(btn_copy)
        layout.addLayout(row_copy)

        # ── Éditeur de couleurs ──
        lbl_colors = QLabel("Couleurs :")
        lbl_colors.setStyleSheet("font-weight:bold;")
        layout.addWidget(lbl_colors)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        color_widget = QWidget()
        self._color_grid = QFormLayout(color_widget)
        self._color_grid.setLabelAlignment(Qt.AlignRight)
        self._color_grid.setVerticalSpacing(6)
        scroll.setWidget(color_widget)
        layout.addWidget(scroll, 1)

        self._color_edits: dict[str, QLineEdit] = {}
        init_colors = (theme_data or {}).get("colors", {})
        for key, label in self._COLOR_KEYS:
            row_w = QWidget()
            row_h = QHBoxLayout(row_w)
            row_h.setContentsMargins(0, 0, 0, 0)
            row_h.setSpacing(6)

            edit = QLineEdit(init_colors.get(key, "#1e1e2e"))
            edit.setMaximumWidth(100)
            edit.setPlaceholderText("#rrggbb")
            self._color_edits[key] = edit

            preview = QLabel()
            preview.setFixedSize(22, 22)
            preview.setStyleSheet(
                f"background:{init_colors.get(key,'#1e1e2e')};"
                "border:1px solid #555; border-radius:3px;"
            )

            def _make_picker(e=edit, p=preview):
                def _pick():
                    col = QColorDialog.getColor(
                        QColor(e.text()), self, "Choisir une couleur"
                    )
                    if col.isValid():
                        e.setText(col.name())
                        p.setStyleSheet(
                            f"background:{col.name()};"
                            "border:1px solid #555; border-radius:3px;"
                        )
                return _pick

            def _make_update(e=edit, p=preview):
                def _upd(text):
                    if len(text) in (4, 7) and text.startswith("#"):
                        p.setStyleSheet(
                            f"background:{text};"
                            "border:1px solid #555; border-radius:3px;"
                        )
                return _upd

            edit.textChanged.connect(_make_update())
            btn_pick = QPushButton("…")
            btn_pick.setFixedWidth(28)
            btn_pick.setToolTip("Ouvrir le sélecteur de couleur")
            btn_pick.clicked.connect(_make_picker())

            row_h.addWidget(edit)
            row_h.addWidget(preview)
            row_h.addWidget(btn_pick)
            row_h.addStretch()
            self._color_grid.addRow(f"{label} ({key}) :", row_w)

        # ── Boutons ──
        btn_row = QHBoxLayout()
        btn_cancel = QPushButton("Annuler")
        btn_cancel.clicked.connect(self.reject)
        btn_save = QPushButton("💾 Enregistrer")
        btn_save.setObjectName("primary")
        btn_save.clicked.connect(self._save)
        btn_row.addStretch()
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_save)
        layout.addLayout(btn_row)

    # ──────────────────────────────────────────────────

    def _copy_from_base(self) -> None:
        base_name = self.base_combo.currentText()
        try:
            base = theme_manager.load_theme(base_name)
            colors = base.get("colors", {})
            for key, _ in self._COLOR_KEYS:
                if key in colors and key in self._color_edits:
                    self._color_edits[key].setText(colors[key])
            if not self.name_edit.text():
                self.name_edit.setText(f"Copie de {base.get('name', base_name)}")
        except Exception as e:
            QMessageBox.warning(self, "Erreur", f"Impossible de charger le thème : {e}")

    def _save(self) -> None:
        name = self.name_edit.text().strip()
        slug = self.slug_edit.text().strip().replace(" ", "_").lower()

        if not name:
            QMessageBox.warning(self, "Champ manquant", "Le nom du thème est obligatoire.")
            return
        if not slug:
            QMessageBox.warning(self, "Champ manquant",
                                "L'identifiant (slug) est obligatoire.")
            return

        colors = {key: self._color_edits[key].text().strip()
                  for key, _ in self._COLOR_KEYS}

        # Valider les couleurs hex
        bad = [k for k, v in colors.items()
               if not re.match(r"^#[0-9a-fA-F]{3,6}$", v)]
        if bad:
            QMessageBox.warning(
                self, "Couleur invalide",
                f"Couleur(s) invalide(s) : {', '.join(bad)}\n"
                "Format attendu : #rrggbb ou #rgb"
            )
            return

        theme_data = {
            "name":        name,
            "description": self.desc_edit.text().strip(),
            "colors":      colors,
        }

        try:
            dest = theme_manager.THEMES_DIR / f"{slug}.json"
            theme_manager.THEMES_DIR.mkdir(parents=True, exist_ok=True)
            import json as _json
            dest.write_text(
                _json.dumps(theme_data, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            QMessageBox.information(
                self, "Thème enregistré",
                f"Le thème '{name}' a été enregistré."
            )
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Erreur",
                                 f"Impossible d'enregistrer le thème :\n{e}")


class ThemeSettingsDialog(QDialog):
    """Dialogue pour choisir, créer, importer et exporter des thèmes."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🎨 Paramètres de thème — Voktora")
        self.setModal(True)
        self.setMinimumSize(520, 460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # ── Titre ──
        title = QLabel("🎨 Choisissez un thème")
        title.setObjectName("sectionLbl")
        layout.addWidget(title)

        # ── Liste des thèmes ──
        self.theme_list = QListWidget()
        self.theme_list.setMinimumHeight(160)
        layout.addWidget(self.theme_list)

        # ── Description ──
        self.desc_label = QLabel("")
        self.desc_label.setWordWrap(True)
        self.desc_label.setObjectName("sectionLbl")
        layout.addWidget(self.desc_label)

        # ── Rangée 1 : actions sur les thèmes ──
        row1 = QHBoxLayout()
        btn_create = QPushButton("➕ Créer")
        btn_create.clicked.connect(self._create_custom_theme)
        btn_edit = QPushButton("✏️ Modifier")
        btn_edit.clicked.connect(self._edit_theme)
        btn_delete = QPushButton("🗑 Supprimer")
        btn_delete.setObjectName("danger")
        btn_delete.clicked.connect(self._delete_theme)
        row1.addWidget(btn_create)
        row1.addWidget(btn_edit)
        row1.addWidget(btn_delete)
        row1.addStretch()
        layout.addLayout(row1)

        # ── Rangée 2 : import / export ──
        row2 = QHBoxLayout()
        btn_import = QPushButton("📥 Importer un thème…")
        btn_import.clicked.connect(self._import_theme)
        btn_export = QPushButton("📤 Exporter ce thème…")
        btn_export.clicked.connect(self._export_theme)
        row2.addWidget(btn_import)
        row2.addWidget(btn_export)
        row2.addStretch()
        layout.addLayout(row2)

        # ── Rangée 3 : Annuler / Appliquer ──
        row3 = QHBoxLayout()
        btn_cancel = QPushButton("Annuler")
        btn_cancel.clicked.connect(self.reject)
        btn_apply = QPushButton("✔ Appliquer")
        btn_apply.setObjectName("primary")
        btn_apply.clicked.connect(self._apply_theme)
        row3.addStretch()
        row3.addWidget(btn_cancel)
        row3.addWidget(btn_apply)
        layout.addLayout(row3)

        # ── Connexions ──
        self._load_themes()
        self.theme_list.currentItemChanged.connect(self._on_theme_changed)

    # ──────────────────────────────────────────────────

    def _load_themes(self) -> None:
        self.theme_list.clear()
        try:
            themes       = theme_manager.get_available_themes()
            current_theme = core.get_app_config().get("theme", "default")

            for theme_name in themes:
                try:
                    theme_data = theme_manager.load_theme(theme_name)
                    display    = f"🎨 {theme_data.get('name', theme_name)}"
                    if theme_name == current_theme:
                        display += "  ✓"
                    item = QListWidgetItem(display)
                    item.setData(Qt.UserRole, theme_name)
                    if theme_name == current_theme:
                        item.setSelected(True)
                    self.theme_list.addItem(item)
                except Exception as e:
                    print(f"Erreur chargement thème {theme_name}: {e}")

        except Exception as e:
            QMessageBox.critical(self, "Erreur",
                                 f"Impossible de charger les thèmes :\n{e}")

    def _on_theme_changed(self, current, previous) -> None:
        if current:
            theme_name = current.data(Qt.UserRole)
            try:
                theme_data = theme_manager.load_theme(theme_name)
                self.desc_label.setText(
                    f"<i>{theme_data.get('description', 'Pas de description')}</i>"
                )
            except Exception:
                self.desc_label.setText("Erreur lors du chargement de la description")
        else:
            self.desc_label.setText("")

    def _apply_theme(self) -> None:
        current_item = self.theme_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "Attention", "Veuillez sélectionner un thème.")
            return
        theme_name = current_item.data(Qt.UserRole)
        try:
            theme_manager.set_theme(theme_name)
            theme_manager.apply_theme_to_app(QApplication.instance())
            QMessageBox.information(
                self, "Thème appliqué",
                f"Le thème '{theme_name}' a été appliqué.\n\n"
                "Redémarrez l'application pour voir tous les changements."
            )
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Erreur",
                                 f"Impossible d'appliquer le thème :\n{e}")

    # ── Créer / Modifier / Supprimer ──────────────────

    def _create_custom_theme(self) -> None:
        dlg = CustomThemeDialog(self)
        if dlg.exec() == QDialog.Accepted:
            self._load_themes()

    def _edit_theme(self) -> None:
        current_item = self.theme_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "Attention",
                                "Veuillez sélectionner un thème à modifier.")
            return
        theme_name = current_item.data(Qt.UserRole)
        if theme_name in ("default", "dark", "light"):
            QMessageBox.warning(self, "Thème protégé",
                                f"Le thème '{theme_name}' est un thème par défaut "
                                "et ne peut pas être modifié.")
            return
        try:
            theme_data = theme_manager.load_theme(theme_name)
            dlg = CustomThemeDialog(self, theme_data, theme_name)
            if dlg.exec() == QDialog.Accepted:
                self._load_themes()
        except Exception as e:
            QMessageBox.critical(self, "Erreur",
                                 f"Impossible de charger le thème pour modification :\n{e}")

    def _delete_theme(self) -> None:
        current_item = self.theme_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "Attention",
                                "Veuillez sélectionner un thème à supprimer.")
            return
        theme_name = current_item.data(Qt.UserRole)
        if theme_name in ("default", "dark", "light"):
            QMessageBox.warning(self, "Thème protégé",
                                f"Le thème '{theme_name}' est protégé et ne peut pas être supprimé.")
            return
        reply = QMessageBox.question(
            self, "Supprimer",
            f"Supprimer le thème '{theme_name}' ?\n\nCette action est irréversible.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        try:
            theme_path = theme_manager.THEMES_DIR / f"{theme_name}.json"
            if theme_path.exists():
                theme_path.unlink()
                QMessageBox.information(self, "Succès",
                                        f"Thème '{theme_name}' supprimé.")
                self._load_themes()
            else:
                QMessageBox.warning(self, "Erreur",
                                    f"Fichier du thème '{theme_name}' introuvable.")
        except Exception as e:
            QMessageBox.critical(self, "Erreur",
                                 f"Impossible de supprimer le thème :\n{e}")

    # ── Import / Export ───────────────────────────────

    def _import_theme(self) -> None:
        """Importe un fichier .json de thème dans le dossier des thèmes."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Importer un thème Voktora",
            str(Path.home()),
            "Thèmes JSON (*.json);;Tous les fichiers (*)",
        )
        if not file_path:
            return

        try:
            theme_name = theme_manager.import_theme(Path(file_path))
            QMessageBox.information(
                self, "Thème importé",
                f"Le thème '{theme_name}' a été importé avec succès !\n"
                "Il est maintenant disponible dans la liste."
            )
            self._load_themes()

        except FileExistsError as e:
            QMessageBox.warning(self, "Thème existant", str(e))
        except ValueError as e:
            QMessageBox.critical(self, "Fichier invalide",
                                 f"Impossible d'importer ce fichier :\n{e}")
        except Exception as e:
            QMessageBox.critical(self, "Erreur", f"Import échoué :\n{e}")

    def _export_theme(self) -> None:
        """Exporte le thème sélectionné vers un fichier .json."""
        current_item = self.theme_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "Attention",
                                "Veuillez sélectionner un thème à exporter.")
            return

        theme_name = current_item.data(Qt.UserRole)

        dest_path, _ = QFileDialog.getSaveFileName(
            self,
            "Exporter le thème",
            str(Path.home() / f"{theme_name}.json"),
            "Thèmes JSON (*.json);;Tous les fichiers (*)",
        )
        if not dest_path:
            return

        try:
            exported = theme_manager.export_theme(theme_name, Path(dest_path))
            QMessageBox.information(
                self, "Thème exporté",
                f"Le thème '{theme_name}' a été exporté vers :\n{exported}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Erreur", f"Export échoué :\n{e}")


