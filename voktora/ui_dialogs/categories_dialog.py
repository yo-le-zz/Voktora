"""
Voktora — ui_dialogs.categories_dialog
Fragment de ui_dialogs.py extrait lors du découpage v1.0.2 en package.
"""

from __future__ import annotations

import core
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)


# ════════════ categories_dialog.py ════════════
class CategoriesDialog(QDialog):
    """Dialogue pour gérer les catégories de projets."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📂 Gestion des catégories — Voktora")
        self.setModal(True)
        self.setFixedSize(500, 450)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # Liste des catégories existantes
        list_group = QGroupBox("📂 Catégories existantes")
        list_layout = QVBoxLayout()
        
        self.categories_list = QListWidget()
        list_layout.addWidget(self.categories_list)
        
        list_group.setLayout(list_layout)
        layout.addWidget(list_group)
        
        # Ajouter une nouvelle catégorie
        add_group = QGroupBox("➕ Ajouter une catégorie")
        add_layout = QFormLayout()
        
        self.new_category_edit = QLineEdit()
        self.new_category_edit.setPlaceholderText("Nom de la nouvelle catégorie...")
        add_layout.addRow("Nom:", self.new_category_edit)
        
        self.btn_add_category = QPushButton("➕ Ajouter")
        self.btn_add_category.clicked.connect(self._add_category)
        add_layout.addRow("", self.btn_add_category)
        
        add_group.setLayout(add_layout)
        layout.addWidget(add_group)
        
        # Boutons
        btn_layout = QHBoxLayout()
        btn_delete = QPushButton("🗑️ Supprimer")
        btn_delete.clicked.connect(self._delete_selected)
        btn_cancel = QPushButton("Annuler")
        btn_cancel.clicked.connect(self.reject)
        btn_apply = QPushButton("Appliquer")
        btn_apply.setObjectName("primary")
        btn_apply.clicked.connect(self.accept)
        
        btn_layout.addWidget(btn_delete)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_apply)
        layout.addLayout(btn_layout)
        
        # Charger les catégories existantes
        self._load_categories()
        
    def _load_categories(self):
        """Charge la liste des catégories existantes."""
        cfg = core._load_config()
        categories = cfg.get("categories", [])
        
        # Catégories par défaut
        default_categories = ["Web", "Desktop", "Mobile", "API", "CLI", "Game", "AI/ML", "Data", "DevOps", "Security", "IoT", "Blockchain", "Autre"]
        
        all_categories = list(set(default_categories + categories))
        all_categories.sort()
        
        for category in all_categories:
            item = QListWidgetItem(category)
            self.categories_list.addItem(item)
            
    def _add_category(self):
        """Ajoute une nouvelle catégorie."""
        category = self.new_category_edit.text().strip()
        if not category:
            QMessageBox.warning(self, "Attention", "Veuillez entrer un nom de catégorie.")
            return
            
        # Vérifier si la catégorie existe déjà
        for i in range(self.categories_list.count()):
            if self.categories_list.item(i).text().lower() == category.lower():
                QMessageBox.warning(self, "Attention", f"La catégorie '{category}' existe déjà.")
                return
                
        # Ajouter la catégorie
        item = QListWidgetItem(category)
        self.categories_list.addItem(item)
        self.new_category_edit.clear()
        
    def _delete_selected(self):
        """Supprime la catégorie sélectionnée."""
        current_item = self.categories_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "Attention", "Veuillez sélectionner une catégorie à supprimer.")
            return
            
        category = current_item.text()
        reply = QMessageBox.question(
            self, "Supprimer",
            f"Êtes-vous sûr de vouloir supprimer la catégorie '{category}' ?\n\n"
            "Les projets utilisant cette catégorie ne seront pas affectés.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.categories_list.takeItem(self.categories_list.row(current_item))
            
    def get_categories(self):
        """Retourne la liste des catégories."""
        categories = []
        for i in range(self.categories_list.count()):
            categories.append(self.categories_list.item(i).text())
        return categories


