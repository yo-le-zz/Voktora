"""TODO Scanner 1.1 — onglet qui liste TODO / FIXME / HACK / BUG… avec filtres, recherche et export.

Montre : api.options, add_project_tab, run_async, set_clipboard_text, une logique pure (scanner.py) testée à part.
"""

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QBrush, QColor, QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import scanner

KIND_COLORS = {"BUG": "#e5484d", "FIXME": "#e5484d", "HACK": "#f76b15", "XXX": "#f76b15", "TODO": "#3e63dd",
               "OPTIMIZE": "#12a594", "NOTE": "#8b8d98"}


class TodoTab(QWidget):
    def __init__(self, api):
        super().__init__()
        self._api, self._path, self._items = api, None, []
        self._clip = api.set_clipboard_text
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)
        self._title = QLabel("Sélectionnez un projet")
        self._title.setStyleSheet("font-weight: 600; font-size: 14px;")
        self._summary = QLabel("")
        self._summary.setWordWrap(True)
        bar = QHBoxLayout()
        self._kind = QComboBox()
        self._kind.addItem("Tous les types", "")
        self._search = QLineEdit()
        self._search.setPlaceholderText("Filtrer par texte, fichier ou auteur…")
        self._search.setClearButtonEnabled(True)
        self._kind.currentIndexChanged.connect(self._render)
        self._search.textChanged.connect(self._render)
        scan_btn = QPushButton("Analyser")
        scan_btn.clicked.connect(self.refresh)
        copy_btn = QPushButton("Copier (Markdown)")
        copy_btn.setToolTip("Copie la liste affichée en liste de tâches Markdown")
        copy_btn.clicked.connect(self._copy)
        for w, s in ((self._kind, 0), (self._search, 1), (scan_btn, 0), (copy_btn, 0)):
            bar.addWidget(w, s)
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Type", "Fichier", "Ligne", "Texte"])
        self._tree.setRootIsDecorated(False)
        self._tree.setAlternatingRowColors(True)
        self._tree.setUniformRowHeights(True)
        self._tree.setColumnWidth(0, 90)
        self._tree.setColumnWidth(1, 280)
        self._tree.setColumnWidth(2, 60)
        self._tree.itemDoubleClicked.connect(self._open)
        self._empty = QLabel("")
        self._empty.setAlignment(Qt.AlignCenter)
        self._empty.setStyleSheet("color: gray;")
        for w in (self._title, self._summary):
            layout.addWidget(w)
        layout.addLayout(bar)
        layout.addWidget(self._tree, stretch=1)
        layout.addWidget(self._empty)

    # ── options ──
    def _markers(self):
        return scanner.parse_list(self._api.options.get("markers"), upper=True) or list(scanner.DEFAULT_MARKERS)

    def set_project(self, path):
        self._path = path
        self.refresh()

    def refresh(self):
        self._items = []
        self._render()
        if self._path is None:
            self._title.setText("Sélectionnez un projet")
            self._summary.setText("")
            return
        root = self._path
        self._title.setText(f"Marqueurs — {root.name}")
        self._summary.setText("Analyse en cours…")
        markers = self._markers()
        skip = scanner.DEFAULT_SKIP + tuple(scanner.parse_list(self._api.options.get("skip_dirs")))
        limit = int(self._api.options.get("max_files"))
        self._api.run_async(lambda: scanner.scan(root, markers, skip, limit),
                            lambda res: self._loaded(root, *res),
                            lambda exc: self._summary.setText(f"Erreur : {exc}"))

    def _loaded(self, root, items, truncated):
        if root != self._path:
            return                                        # on a changé de projet entre-temps
        self._items = items
        counts = scanner.summarize(items)
        present = [self._kind.itemData(i) for i in range(1, self._kind.count())]
        if list(counts) != present:
            self._kind.blockSignals(True)
            self._kind.clear()
            self._kind.addItem("Tous les types", "")
            for kind, n in counts.items():
                self._kind.addItem(f"{kind} ({n})", kind)
            self._kind.blockSignals(False)
        text = " · ".join(f"{k} {n}" for k, n in counts.items()) or "Aucun marqueur trouvé"
        self._summary.setText(text + ("  — analyse tronquée (limite de fichiers atteinte)" if truncated else ""))
        self._render()

    def _visible(self):
        return scanner.filter_items(self._items, self._kind.currentData() or "", self._search.text())

    def _render(self, *_):
        self._tree.setUpdatesEnabled(False)
        self._tree.clear()
        rows = self._visible()
        for item in rows:
            node = QTreeWidgetItem([item.kind, item.path, str(item.line), item.text + (f"  ({item.author})" if item.author else "")])
            node.setForeground(0, QBrush(QColor(KIND_COLORS.get(item.kind, "#8b8d98"))))
            node.setData(1, Qt.UserRole, item.path)
            self._tree.addTopLevelItem(node)
        self._tree.setUpdatesEnabled(True)
        if self._path is None:
            self._empty.setText("")
        elif not rows:
            self._empty.setText("Rien à afficher." if self._items else "")
        else:
            self._empty.setText(f"{len(rows)} élément(s) affiché(s) — double-clic : ouvrir le fichier")

    def _copy(self):
        text = scanner.to_markdown(self._visible(), self._path.name if self._path else "")
        self._clip(text)
        self._api.notify("Liste copiée (Markdown)")

    def _open(self, node, _column):
        if self._path is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._path / node.data(1, Qt.UserRole))))


def on_load(api):
    o = api.options
    o.group("Analyse")
    o.add_text("markers", "Marqueurs recherchés", default=", ".join(scanner.DEFAULT_MARKERS),
               help="Séparés par des virgules. Reconnus seulement dans un commentaire ou une case Markdown.")
    o.add_text("skip_dirs", "Dossiers ignorés en plus", default="", help="Ex. : vendor, out. .git, node_modules, .venv… le sont toujours.")
    o.add_int("max_files", "Nombre maximal de fichiers", default=4000, min=100, max=100000, step=500)
    api.add_project_tab("TODO", lambda ctx: TodoTab(api), icon="mdi:format-list-checks")
