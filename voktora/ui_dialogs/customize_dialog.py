"""
Voktora — ui_dialogs.customize_dialog
Fragment de ui_dialogs.py extrait lors du découpage v1.0.2 en package.
"""

from __future__ import annotations

from pathlib import Path

import ai_providers
import core
import icon_catalog
import icons
from PySide6.QtCore import QSize, Qt, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QCompleter,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)


class _AIWorker(QThread):
    """Exécute un appel au fournisseur d'IA actif (description / suggestion d'icône)
    en arrière-plan pour ne pas geler l'interface."""
    finished_ok  = Signal(str)
    finished_err = Signal(str)

    def __init__(self, kind: str, project_name: str, context: str, provider: dict):
        super().__init__()
        self._kind = kind  # "description" ou "icon"
        self._project_name = project_name
        self._context = context
        self._provider = provider

    def run(self) -> None:
        try:
            if self._kind == "description":
                result = ai_providers.generate_description(self._provider, self._project_name, self._context)
            else:
                choices = [e.id for e in icon_catalog.all_entries()]
                result = ai_providers.suggest_icon(self._provider, self._project_name, choices, self._context)
            self.finished_ok.emit(result)
        except ai_providers.AIError as e:
            self.finished_err.emit(str(e))


# ════════════ customize_dialog.py ════════════
class CustomizeProjectDialog(QDialog):
    """Dialogue pour personnaliser un projet sélectionné."""
    
    def __init__(self, project_path: str, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.setWindowTitle("🎨 Personnaliser le projet — Voktora")
        self.setModal(True)
        self.setFixedSize(500, 600)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # Informations du projet
        info_group = QGroupBox("📋 Informations du projet")
        info_layout = QFormLayout()
        
        self.name_edit = QLineEdit()
        self.name_edit.setReadOnly(True)
        info_layout.addRow("Nom:", self.name_edit)
        
        self.path_label = QLabel(project_path)
        self.path_label.setWordWrap(True)
        info_layout.addRow("Chemin:", self.path_label)
        
        info_group.setLayout(info_layout)
        layout.addWidget(info_group)
        
        # Personnalisation
        custom_group = QGroupBox("🎨 Personnalisation")
        custom_layout = QFormLayout()
        
        # Couleur
        self.color_button = QPushButton("Choisir une couleur")
        self.color_button.clicked.connect(self._choose_color)
        self.color_preview = QLabel("■")
        self.color_preview.setStyleSheet("font-size: 24px;")
        
        color_layout = QHBoxLayout()
        color_layout.addWidget(self.color_preview)
        color_layout.addWidget(self.color_button)
        color_layout.addStretch()
        custom_layout.addRow("Couleur:", color_layout)
        
        # Icône (police d'icônes embarquée : s'affiche sur tous les systèmes)
        self._icon_value = ""
        self.icon_preview = QPushButton()
        self.icon_preview.setFixedSize(40, 40)
        self.icon_preview.setIconSize(QSize(24, 24))
        self.icon_preview.setToolTip("Choisir une icône")
        self.icon_preview.clicked.connect(self._open_icon_picker)
        icon_row = QHBoxLayout()
        icon_row.addWidget(self.icon_preview)
        btn_icon_picker = QPushButton("Choisir…")
        btn_icon_picker.setToolTip("Ouvrir le sélecteur d'icônes")
        btn_icon_picker.clicked.connect(self._open_icon_picker)
        icon_row.addWidget(btn_icon_picker)
        btn_icon_clear = QPushButton("Aucune")
        btn_icon_clear.clicked.connect(lambda: self._set_icon(""))
        icon_row.addWidget(btn_icon_clear)
        icon_row.addStretch()
        custom_layout.addRow("Icône:", icon_row)

        # Catégorie
        self.category_combo = QComboBox()
        self.category_combo.setEditable(True)
        
        # Catégories créées par l'utilisateur (voir « Gérer les catégories »).
        # Saisir un nom inconnu en crée une nouvelle à l'enregistrement.
        all_categories = [c["name"] for c in core.list_categories()]
        self.category_combo.addItem("")
        self.category_combo.addItems(all_categories)
        self.category_combo.lineEdit().setPlaceholderText("Aucune — tapez un nom pour en créer une")

        # Configurer l'autocomplétion
        completer = QCompleter(all_categories)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        self.category_combo.setCompleter(completer)

        self.language_combo = QComboBox()
        self.language_combo.setEditable(True)
        self.language_combo.addItems([
            "Python", "JavaScript", "TypeScript", "C#", "Java", "Go",
            "PHP", "Ruby", "Shell", "PowerShell", "Rust", "Dart",
            "Kotlin", "Swift", "C++", "C", "HTML", "CSS", "JSON", "Autre"
        ])
        self.language_combo.setCurrentText("")
        custom_layout.addRow("Langage:", self.language_combo)
        
        custom_layout.addRow("Catégorie:", self.category_combo)
        
        # Tags
        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText("tag1, tag2, tag3…")
        self.tags_edit.setToolTip("Mots-clés séparés par des virgules — utilisables dans la recherche.")
        custom_layout.addRow("Tags:", self.tags_edit)
        
        custom_group.setLayout(custom_layout)
        layout.addWidget(custom_group)
        
        # Statut
        status_group = QGroupBox("📊 Statut du projet")
        status_layout = QFormLayout()
        
        self.status_combo = QComboBox()
        # Charger tous les statuts (par défaut + personnalisés)
        all_statuses = core.get_all_project_statuses()
        for status_id, status in all_statuses.items():
            self.status_combo.addItem(icons.icon(status.emoji, color=status.color), status.name, status_id)
        status_layout.addRow("Statut:", self.status_combo)
        
        # Notes
        self.notes_edit = QLineEdit()
        self.notes_edit.setPlaceholderText("Notes personnelles sur le projet...")
        status_layout.addRow("Notes:", self.notes_edit)
        
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)
        
        # Génération IA (fournisseur actif : Ollama, OmniRoute, compatible OpenAI)
        ollama_group = QGroupBox("Génération par IA")
        ollama_layout = QHBoxLayout()
        self.btn_ollama_desc = QPushButton("Générer description")
        self.btn_ollama_desc.setToolTip(
            "Génère une courte description avec le fournisseur d'IA actif (Réglages) "
            "et remplit le champ Notes ci-dessus."
        )
        self.btn_ollama_desc.clicked.connect(lambda: self._run_ai("description"))
        self.btn_ollama_emoji = QPushButton("Suggérer une icône")
        self.btn_ollama_emoji.setToolTip("Suggère une icône pertinente avec le fournisseur d'IA actif.")
        self.btn_ollama_emoji.clicked.connect(lambda: self._run_ai("icon"))
        self._ollama_status_lbl = QLabel("")
        self._ollama_status_lbl.setStyleSheet("font-size: 11px; color:#a6adc8;")
        ollama_layout.addWidget(self.btn_ollama_desc)
        ollama_layout.addWidget(self.btn_ollama_emoji)
        ollama_layout.addWidget(self._ollama_status_lbl, stretch=1)
        ollama_group.setLayout(ollama_layout)
        layout.addWidget(ollama_group)
        self._ai_bar = QProgressBar()
        self._ai_bar.setRange(0, 0)
        self._ai_bar.setTextVisible(False)
        self._ai_bar.setFixedHeight(6)
        self._ai_bar.hide()
        layout.addWidget(self._ai_bar)
        self._ollama_worker: _AIWorker | None = None

        # Boutons
        btn_layout = QHBoxLayout()
        btn_cancel = QPushButton("Annuler")
        btn_cancel.clicked.connect(self.reject)
        btn_reset = QPushButton("Réinitialiser")
        btn_reset.clicked.connect(self._reset_customization)
        btn_apply = QPushButton("Appliquer")
        btn_apply.setObjectName("primary")
        btn_apply.clicked.connect(self._apply_customization)
        
        btn_layout.addWidget(btn_cancel)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_reset)
        btn_layout.addWidget(btn_apply)
        layout.addLayout(btn_layout)
        
        # Charger les données actuelles
        self._load_current_data()
        
    def _load_current_data(self):
        """Charge les données de personnalisation actuelles du projet."""
        entry = core._find_entry(core._load_config(), Path(self.project_path))
        if entry:
            self.name_edit.setText(entry.get("name", ""))
            
            # Couleur
            color = entry.get("color")
            if color:
                self.color_preview.setStyleSheet(
                f"font-size: 20px; color: {color};"
                f" background: {color}; border-radius: 6px;"
                f" padding: 2px 8px; border: 2px solid #45475a;"
            )
                self.current_color = color
            else:
                self.current_color = "#89b4fa"
                self.color_preview.setStyleSheet(
                    "font-size: 20px; color: #89b4fa; background: #89b4fa;"
                    " border-radius: 6px; padding: 2px 8px; border: 2px solid #45475a;"
                )
            
            # Emoji
            self._set_icon(entry.get("emoji") or "")
            
            # Catégorie
            category = entry.get("category")
            if category:
                index = self.category_combo.findText(category)
                if index >= 0:
                    self.category_combo.setCurrentIndex(index)
                else:
                    self.category_combo.setCurrentText(category)
            
            # Statut
            status = entry.get("status", core.DEFAULT_PROJECT_STATUS)
            index = self.status_combo.findData(status)
            if index >= 0:
                self.status_combo.setCurrentIndex(index)
            else:
                self.status_combo.setCurrentIndex(0)  # Premier statut (par défaut)
            
            # Langage
            self.language_combo.setCurrentText(entry.get("language", "") or "")
            
            # Notes
            self.notes_edit.setText(entry.get("note", ""))

            # Tags
            self.tags_edit.setText(", ".join(entry.get("tags") or []))
        else:
            # Valeurs par défaut
            self.current_color = "#89b4fa"
            self.color_preview.setStyleSheet("font-size: 24px; color: #89b4fa;")
            
    def _choose_color(self):
        """Ouvre le dialogue de sélection de couleur."""
        color = QColorDialog.getColor(QColor(self.current_color), self, "Choisir une couleur")
        if color.isValid():
            self.current_color = color.name()
            self.color_preview.setStyleSheet(f"font-size: 24px; color: {self.current_color};")
            
    def _reset_customization(self):
        """Réinitialise la personnalisation aux valeurs par défaut."""
        self.current_color = "#89b4fa"
        self.color_preview.setStyleSheet("font-size: 24px; color: #89b4fa;")
        self._set_icon("")
        self.category_combo.setCurrentText("")
        self.status_combo.setCurrentIndex(0)  # Premier statut (par défaut)
        self.notes_edit.setText("")
        self.tags_edit.setText("")
        
    def _set_icon(self, value: str) -> None:
        """Définit l'icône du projet (identifiant « mdi:… » ; un emoji hérité est converti)."""
        self._icon_value = icons.resolve_id(value) or ""
        self.icon_preview.setIcon(icons.icon(self._icon_value))
        self.icon_preview.setText("" if self._icon_value else "—")

    def _open_icon_picker(self) -> None:
        from ui_dialogs.emoji_picker_dialog import IconPickerDialog
        chosen = IconPickerDialog.pick(self, self._icon_value)
        if chosen is not None:
            self._set_icon(chosen)

    def _run_ai(self, kind: str) -> None:
        if self._ollama_worker is not None:
            return  # une génération est déjà en cours
        provider = core.get_active_ai_provider()
        if not provider or not provider["model"]:
            QMessageBox.warning(
                self, "IA non configurée",
                "Aucun modèle n'est sélectionné pour le fournisseur d'IA actif.\n\n"
                "Configurez-le dans les Réglages (⚙) → section « Fournisseurs d'IA »."
            )
            return

        context = self.notes_edit.text()
        readme = core.find_readme(Path(self.project_path))
        if readme is not None:
            try:
                context = (context + "\n" + readme.read_text(encoding="utf-8", errors="replace"))[:4000]
            except OSError:
                pass

        self.btn_ollama_desc.setEnabled(False)
        self.btn_ollama_emoji.setEnabled(False)
        self._ai_bar.show()
        self._ollama_status_lbl.setText(f"Génération en cours ({provider['name']})…")
        self._ollama_status_lbl.setStyleSheet("font-size: 11px; color:#a6adc8;")

        self._ollama_worker = _AIWorker(kind, Path(self.project_path).name, context, provider)
        self._ollama_worker.finished_ok.connect(lambda r: self._on_ollama_done(kind, r))
        self._ollama_worker.finished_err.connect(self._on_ollama_error)
        self._ollama_worker.start()

    def _on_ollama_done(self, kind: str, result: str) -> None:
        if kind == "description":
            self.notes_edit.setText(result)
        else:
            self._set_icon(result)
        self._ollama_status_lbl.setText("Terminé.")
        self._ollama_status_lbl.setStyleSheet("font-size: 11px; color:#a6e3a1;")
        self._ollama_reset_buttons()

    def _on_ollama_error(self, message: str) -> None:
        QMessageBox.warning(self, "Fournisseur d'IA", message)
        self._ollama_status_lbl.setText("")
        self._ollama_reset_buttons()

    def _ollama_reset_buttons(self) -> None:
        self._ai_bar.hide()
        self.btn_ollama_desc.setEnabled(True)
        self.btn_ollama_emoji.setEnabled(True)
        self._ollama_worker = None

    @staticmethod
    def _parse_tags(text: str) -> list:
        """Convertit 'tag1, tag2, , tag1' en liste dédupliquée et propre."""
        seen = []
        for raw in text.split(","):
            tag = raw.strip()
            if tag and tag not in seen:
                seen.append(tag)
        return seen

    def _apply_customization(self):
        """Applique la personnalisation au projet."""
        try:
            cfg = core._load_config()
            
            # Trouver l'entrée correspondante
            entry = core._find_entry(cfg, Path(self.project_path))
            if entry:
                # La catégorie passe par core.assign_category : elle est créée si besoin.
                core.assign_category([self.project_path], self.category_combo.currentText().strip() or None)
                entry["color"] = self.current_color if self.current_color != "#89b4fa" else None
                entry["emoji"] = self._icon_value or None
                entry["language"] = self.language_combo.currentText() or None
                entry["status"] = self.status_combo.currentData()
                entry["note"] = self.notes_edit.text()
                entry["tags"] = self._parse_tags(self.tags_edit.text())
                
                core._save_config(cfg)
                QMessageBox.information(
                    self, "Personnalisation appliquée",
                    "La personnalisation du projet a été enregistrée avec succès."
                )
                self.accept()
            else:
                QMessageBox.critical(self, "Erreur", "Projet introuvable dans la configuration.")
                
        except Exception as e:
            QMessageBox.critical(self, "Erreur", f"Impossible d'appliquer la personnalisation :\n{e}")


