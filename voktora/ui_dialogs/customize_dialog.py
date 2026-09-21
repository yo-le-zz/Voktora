"""
Voktora — ui_dialogs.customize_dialog
Fragment de ui_dialogs.py extrait lors du découpage v1.0.2 en package.
"""

from __future__ import annotations

from pathlib import Path

import core
import ollama_client
from PySide6.QtCore import Qt, QThread, Signal
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
    QPushButton,
    QVBoxLayout,
)


class _OllamaWorker(QThread):
    """Exécute un appel Ollama (génération description / suggestion emoji)
    en arrière-plan pour ne pas geler l'interface."""
    finished_ok  = Signal(str)
    finished_err = Signal(str)

    def __init__(self, kind: str, project_name: str, context: str, host: str, model: str):
        super().__init__()
        self._kind = kind  # "description" ou "emoji"
        self._project_name = project_name
        self._context = context
        self._host = host
        self._model = model

    def run(self) -> None:
        try:
            if self._kind == "description":
                result = ollama_client.generate_description(
                    self._project_name, self._context, model=self._model, host=self._host
                )
            else:
                result = ollama_client.suggest_emoji(
                    self._project_name, self._context, model=self._model, host=self._host
                )
            self.finished_ok.emit(result)
        except ollama_client.OllamaError as e:
            self.finished_err.emit(str(e))


# ════════════ customize_dialog.py ════════════
class CustomizeProjectDialog(QDialog):
    """Dialogue pour personnaliser un projet sélectionné."""
    
    def __init__(self, project_path: str, project_kind: str, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.project_kind = project_kind
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
        
        # Emoji
        self.emoji_combo = QComboBox()
        self.emoji_combo.setEditable(True)
        self.emoji_combo.addItems([
            "📦", "🎯", "🚀", "⚡", "🔥", "💎", "🌟", 
            "🎨", "🛠️", "📚", "🔬", "🎮", "🌐", "📱",
            "💻", "⌨️", "🖥️", "📊", "📈", "🗂️", "📁",
            "🔐", "🔒", "🔑", "🛡️", "⚙️", "🔧", "🔨"
        ])
        emoji_row = QHBoxLayout()
        emoji_row.addWidget(self.emoji_combo, stretch=1)
        btn_emoji_picker = QPushButton("😀 Menu…")
        btn_emoji_picker.setToolTip("Ouvrir le sélecteur d'emoji complet")
        btn_emoji_picker.clicked.connect(self._open_emoji_picker)
        emoji_row.addWidget(btn_emoji_picker)
        custom_layout.addRow("Emoji:", emoji_row)
        
        # Catégorie
        self.category_combo = QComboBox()
        self.category_combo.setEditable(True)
        
        # Charger les catégories par défaut et personnalisées
        default_categories = [
            "Web", "Desktop", "Mobile", "API", "CLI", "Game", "AI/ML",
            "Data", "DevOps", "Security", "IoT", "Blockchain", "Autre"
        ]
        
        # Récupérer les catégories personnalisées depuis la config
        cfg = core._load_config()
        custom_categories = cfg.get("categories", [])
        
        # Combiner et dédupliquer les catégories
        all_categories = list(set(default_categories + custom_categories))
        all_categories.sort()
        
        self.category_combo.addItems(all_categories)
        
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
            self.status_combo.addItem(f"{status.emoji} {status.name}", status_id)
        status_layout.addRow("Statut:", self.status_combo)
        
        # Notes
        self.notes_edit = QLineEdit()
        self.notes_edit.setPlaceholderText("Notes personnelles sur le projet...")
        status_layout.addRow("Notes:", self.notes_edit)
        
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)
        
        # Génération IA (Ollama)
        ollama_group = QGroupBox("🤖 Génération via Ollama (local)")
        ollama_layout = QHBoxLayout()
        self.btn_ollama_desc = QPushButton("📝 Générer description")
        self.btn_ollama_desc.setToolTip(
            "Génère une courte description via un modèle Ollama local et "
            "remplit le champ Notes ci-dessus."
        )
        self.btn_ollama_desc.clicked.connect(lambda: self._run_ollama("description"))
        self.btn_ollama_emoji = QPushButton("🎯 Suggérer emoji")
        self.btn_ollama_emoji.setToolTip(
            "Suggère un emoji pertinent via un modèle Ollama local."
        )
        self.btn_ollama_emoji.clicked.connect(lambda: self._run_ollama("emoji"))
        self._ollama_status_lbl = QLabel("")
        self._ollama_status_lbl.setStyleSheet("font-size: 11px; color:#a6adc8;")
        ollama_layout.addWidget(self.btn_ollama_desc)
        ollama_layout.addWidget(self.btn_ollama_emoji)
        ollama_layout.addWidget(self._ollama_status_lbl, stretch=1)
        ollama_group.setLayout(ollama_layout)
        layout.addWidget(ollama_group)
        self._ollama_worker: _OllamaWorker | None = None
        
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
        entry = core._find_entry(core._load_config(), self.project_kind + "s", Path(self.project_path))
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
            emoji = entry.get("emoji")
            if emoji:
                index = self.emoji_combo.findText(emoji)
                if index >= 0:
                    self.emoji_combo.setCurrentIndex(index)
                else:
                    self.emoji_combo.setCurrentText(emoji)
            
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
        self.emoji_combo.setCurrentText("")
        self.category_combo.setCurrentText("")
        self.status_combo.setCurrentIndex(0)  # Premier statut (par défaut)
        self.notes_edit.setText("")
        self.tags_edit.setText("")
        
    def _open_emoji_picker(self) -> None:
        from ui_dialogs.emoji_picker_dialog import EmojiPickerDialog
        emoji = EmojiPickerDialog.pick(self)
        if emoji:
            self.emoji_combo.setCurrentText(emoji)

    def _run_ollama(self, kind: str) -> None:
        if self._ollama_worker is not None:
            return  # une génération est déjà en cours
        ollama_cfg = core.get_ollama_config()
        if not ollama_cfg["model"]:
            QMessageBox.warning(
                self, "Ollama non configuré",
                "Aucun modèle Ollama sélectionné.\n\n"
                "Configurez-le dans les Réglages (⚙) → section « 🤖 Ollama »."
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
        self._ollama_status_lbl.setText("🤖 Génération en cours…")
        self._ollama_status_lbl.setStyleSheet("font-size: 11px; color:#a6adc8;")

        self._ollama_worker = _OllamaWorker(
            kind, Path(self.project_path).name, context,
            ollama_cfg["host"], ollama_cfg["model"],
        )
        self._ollama_worker.finished_ok.connect(lambda r: self._on_ollama_done(kind, r))
        self._ollama_worker.finished_err.connect(self._on_ollama_error)
        self._ollama_worker.start()

    def _on_ollama_done(self, kind: str, result: str) -> None:
        if kind == "description":
            self.notes_edit.setText(result)
        else:
            self.emoji_combo.setCurrentText(result)
        self._ollama_status_lbl.setText("✅ Terminé.")
        self._ollama_status_lbl.setStyleSheet("font-size: 11px; color:#a6e3a1;")
        self._ollama_reset_buttons()

    def _on_ollama_error(self, message: str) -> None:
        QMessageBox.warning(self, "Ollama", message)
        self._ollama_status_lbl.setText("")
        self._ollama_reset_buttons()

    def _ollama_reset_buttons(self) -> None:
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
            entry = core._find_entry(cfg, self.project_kind + "s", Path(self.project_path))
            if entry:
                entry["color"] = self.current_color if self.current_color != "#89b4fa" else None
                entry["emoji"] = self.emoji_combo.currentText() or None
                entry["category"] = self.category_combo.currentText() or None
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


