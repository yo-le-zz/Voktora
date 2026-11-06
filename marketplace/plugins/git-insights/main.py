"""Git Insights — onglet de statistiques Git.

Montre : api.run (commandes sans interpréteur), run_async, add_project_tab.
"""

from PySide6.QtWidgets import QLabel, QTextEdit, QVBoxLayout, QWidget


def collect(api, path):
    def git(*args):
        code, out = api.run(["git", *args], cwd=path, timeout=15)
        return out.strip() if code == 0 else ""

    if not git("rev-parse", "--is-inside-work-tree"):
        return "Ce dossier n'est pas un dépôt Git."
    authors = git("shortlog", "-sn", "--no-merges", "HEAD").splitlines()[:5]
    lines = [
        f"Branche : {git('rev-parse', '--abbrev-ref', 'HEAD') or '?'}",
        f"Commits : {git('rev-list', '--count', 'HEAD') or '?'}",
        f"Dernier commit : {git('log', '-1', '--format=%h  %s  (%cr)') or '—'}",
        f"Fichiers modifiés non commités : {len(git('status', '--porcelain').splitlines())}",
        "",
        "Principaux auteurs :",
        *[f"  {line.strip()}" for line in authors],
    ]
    return "\n".join(lines)


class InsightsTab(QWidget):
    def __init__(self, api):
        super().__init__()
        self._api, self._path = api, None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        self._title = QLabel("Sélectionnez un projet")
        self._text = QTextEdit()
        self._text.setReadOnly(True)
        layout.addWidget(self._title)
        layout.addWidget(self._text, stretch=1)

    def set_project(self, path):
        self._path = path
        if path is None:
            self._title.setText("Sélectionnez un projet")
            self._text.clear()
            return
        self._title.setText(f"Git — {path.name}")
        self._text.setPlainText("Analyse…")
        self._api.run_async(lambda: collect(self._api, path),
                            lambda text: self._text.setPlainText(text) if path == self._path else None,
                            lambda exc: self._text.setPlainText(f"Erreur : {exc}"))


def on_load(api):
    api.add_project_tab("Git Insights", lambda ctx: InsightsTab(api), icon="mdi:source-branch")
