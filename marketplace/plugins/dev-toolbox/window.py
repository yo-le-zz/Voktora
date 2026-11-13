"""Fenêtre à onglets : entrée en haut, résultat en bas."""

from PySide6.QtWidgets import QDialog, QHBoxLayout, QPlainTextEdit, QPushButton, QTabWidget, QVBoxLayout, QWidget


class _Tab(QWidget):
    def __init__(self, api, name, fn):
        super().__init__()
        size = api.options.get("font_size")
        self.api, self.fn = api, fn
        self.inp, self.out = QPlainTextEdit(), QPlainTextEdit()
        self.out.setReadOnly(True)
        for box in (self.inp, self.out):
            font = box.font()
            font.setPointSize(size)
            box.setFont(font)
        run = QPushButton("Exécuter")
        copy = QPushButton("Copier le résultat")
        run.clicked.connect(self.run)
        copy.clicked.connect(lambda: api.set_clipboard_text(self.out.toPlainText()))
        row = QHBoxLayout()
        row.addWidget(run)
        row.addWidget(copy)
        layout = QVBoxLayout(self)
        for w in (self.inp, self.out):
            layout.addWidget(w)
        layout.addLayout(row)
        self.inp.textChanged.connect(self.run)

    def values(self):
        o = self.api.options
        return {"pw_length": o.get("pw_length"), "pw_symbols": o.get("pw_symbols")}

    def run(self):
        try:
            self.out.setPlainText(self.fn(self.inp.toPlainText(), self.values()))
        except Exception as exc:  # noqa: BLE001 — afficher, ne pas planter
            self.out.setPlainText(f"Erreur : {exc}")
        if self.api.options.get("copy_result"):
            self.api.set_clipboard_text(self.out.toPlainText())


class ToolboxDialog(QDialog):
    def __init__(self, api, tools, start=None):
        super().__init__()
        self.setWindowTitle("Dev Toolbox")
        self.resize(720, 560)
        tabs = QTabWidget()
        names = list(tools)
        for name in names:
            tabs.addTab(_Tab(api, name, tools[name]), name)
        wanted = start or api.options.get("default_tool")
        if wanted in names:
            tabs.setCurrentIndex(names.index(wanted))
        QVBoxLayout(self).addWidget(tabs)
