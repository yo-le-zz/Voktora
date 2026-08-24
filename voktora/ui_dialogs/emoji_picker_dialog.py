"""
Voktora — ui_dialogs.emoji_picker_dialog
Menu de sélection d'emoji, organisé par catégories avec recherche par
mot-clé, réutilisable partout dans l'UI (personnalisation de projet,
etc.).
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

# Catégorie -> liste de (emoji, mots-clés de recherche en minuscules).
_EMOJI_CATEGORIES: dict[str, list[tuple[str, str]]] = {
    "Projets & Tech": [
        ("📦", "package boite projet"), ("🎯", "cible objectif but"),
        ("🚀", "fusee lancement rapide"), ("⚡", "eclair rapide energie"),
        ("🔥", "feu populaire chaud"), ("💎", "diamant precieux qualite"),
        ("🌟", "etoile favori important"), ("🎨", "palette design creatif"),
        ("🛠️", "outils bricolage maintenance"), ("📚", "livres documentation"),
        ("🔬", "science recherche laboratoire"), ("🎮", "jeu gaming"),
        ("🌐", "web internet reseau"), ("📱", "mobile telephone app"),
        ("💻", "ordinateur portable dev"), ("⌨️", "clavier code"),
        ("🖥️", "ecran bureau ordinateur"), ("📊", "graphique stats donnees"),
        ("📈", "croissance progres statistiques"), ("🗂️", "dossier classement"),
        ("📁", "dossier fichiers"), ("🐛", "bug debogage"),
        ("🧪", "test experimentation"), ("🧩", "puzzle module plugin"),
    ],
    "Sécurité": [
        ("🔐", "securise chiffre cadenas cle"), ("🔒", "verrouille prive"),
        ("🔓", "deverrouille ouvert"), ("🔑", "cle acces"),
        ("🛡️", "bouclier protection securite"), ("⚙️", "engrenage config parametres"),
        ("🔧", "cle a molette outil"), ("🔨", "marteau construction"),
    ],
    "Statuts": [
        ("✅", "termine valide ok"), ("❌", "erreur echec annule"),
        ("⏳", "en cours attente"), ("⚠️", "attention avertissement"),
        ("🚧", "en construction travaux"), ("🟢", "vert actif ok"),
        ("🟡", "jaune pause attention"), ("🔴", "rouge stop bloque"),
        ("⭐", "favori important etoile"), ("🏁", "termine fin drapeau"),
    ],
    "Visages & réactions": [
        ("😀", "content sourire heureux"), ("😎", "cool stylé"),
        ("🤔", "reflexion pensif"), ("😅", "soulage sueur"),
        ("😴", "endormi pause inactif"), ("🥳", "fete celebration"),
        ("👍", "pouce ok approuve"), ("👎", "pouce refuse"),
        ("💡", "idee ampoule astuce"), ("❤️", "coeur favori aime"),
    ],
    "Nature & divers": [
        ("🌱", "pousse debut nouveau"), ("🌳", "arbre croissance"),
        ("🌈", "arc en ciel"), ("☀️", "soleil jour"),
        ("🌙", "lune nuit"), ("⏰", "horloge temps rappel"),
        ("📅", "calendrier date planning"), ("✉️", "email message"),
        ("🔔", "notification alerte cloche"), ("🏆", "trophee recompense"),
    ],
}


class EmojiPickerDialog(QDialog):
    """Menu de sélection d'emoji par catégories, avec recherche."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Choisir un emoji")
        self.setModal(True)
        self.setMinimumSize(380, 420)
        self._selected: str | None = None

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Rechercher (ex. « securise », « rapide »…)")
        self._search.textChanged.connect(self._on_search)
        v.addWidget(self._search)

        self._tabs = QTabWidget()
        self._grids: dict[str, QGridLayout] = {}
        for category, items in _EMOJI_CATEGORIES.items():
            page, grid = self._build_grid_page(items)
            self._grids[category] = grid
            self._tabs.addTab(page, category)
        v.addWidget(self._tabs, stretch=1)

        self._search_page, self._search_grid = self._build_grid_page([])
        self._tabs.addTab(self._search_page, "🔎 Résultats")
        self._search_tab_index = self._tabs.count() - 1
        self._tabs.setTabVisible(self._search_tab_index, False)

    def _build_grid_page(self, items: list[tuple[str, str]]) -> tuple[QWidget, QGridLayout]:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        grid = QGridLayout(container)
        grid.setSpacing(4)
        self._populate_grid(grid, items)
        scroll.setWidget(container)
        return scroll, grid

    def _populate_grid(self, grid: QGridLayout, items: list[tuple[str, str]]) -> None:
        while grid.count():
            item = grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        cols = 8
        for i, (emoji, _keywords) in enumerate(items):
            btn = QPushButton(emoji)
            btn.setFixedSize(36, 36)
            btn.setStyleSheet("font-size: 18px;")
            btn.clicked.connect(lambda checked=False, e=emoji: self._choose(e))
            grid.addWidget(btn, i // cols, i % cols)

    def _on_search(self, text: str) -> None:
        t = text.strip().lower()
        if not t:
            self._tabs.setTabVisible(self._search_tab_index, False)
            self._tabs.setCurrentIndex(0)
            return
        matches = [
            (emoji, kw) for items in _EMOJI_CATEGORIES.values()
            for emoji, kw in items if t in kw or t in emoji
        ]
        self._populate_grid(self._search_grid, matches)
        self._tabs.setTabVisible(self._search_tab_index, True)
        self._tabs.setCurrentIndex(self._search_tab_index)
        if not matches:
            self._search_grid.addWidget(QLabel("Aucun résultat."), 0, 0)

    def _choose(self, emoji: str) -> None:
        self._selected = emoji
        self.accept()

    def get_selected_emoji(self) -> str | None:
        return self._selected

    @staticmethod
    def pick(parent=None) -> str | None:
        """Ouvre le sélecteur et renvoie l'emoji choisi, ou None si annulé."""
        dlg = EmojiPickerDialog(parent)
        if dlg.exec() == QDialog.Accepted:
            return dlg.get_selected_emoji()
        return None
