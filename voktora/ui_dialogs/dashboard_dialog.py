"""
Voktora — ui_dialogs.dashboard_dialog
Fragment de ui_dialogs.py extrait lors du découpage v1.0.2 en package.
"""

from __future__ import annotations

import dashboard
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

# ════════════════════════════════════════════════════════════════════════════
# DASHBOARD UI
# ════════════════════════════════════════════════════════════════════════════

class DashboardDialog(QDialog):
    """Tableau de bord sante et usage."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Dashboard — Sante & Usage")
        self.setMinimumSize(640, 500)

        v = QVBoxLayout(self)
        v.setSpacing(10)
        v.setContentsMargins(14, 12, 14, 12)

        title = QLabel("Dashboard Voktora")
        title.setStyleSheet("font-size:15px; font-weight:bold; color:#cdd6f4;")
        v.addWidget(title)

        self._summary = QLabel("Cliquez sur Analyser pour generer le rapport.")
        self._summary.setStyleSheet("color:#a6adc8; font-size:12px;")
        self._summary.setWordWrap(True)
        v.addWidget(self._summary)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Projet", "Score", "Problemes"])
        self._tree.setColumnWidth(0, 220)
        self._tree.setColumnWidth(1, 70)
        v.addWidget(self._tree)

        self._detail = QTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setFixedHeight(110)
        self._detail.setStyleSheet("font-size:12px;")
        v.addWidget(self._detail)

        row = QHBoxLayout()
        btn_analyze = QPushButton("Analyser")
        btn_analyze.setObjectName("primary")
        btn_analyze.clicked.connect(self._analyze)
        btn_close = QPushButton("Fermer")
        btn_close.clicked.connect(self.accept)
        row.addWidget(btn_analyze)
        row.addStretch()
        row.addWidget(btn_close)
        v.addLayout(row)

        self._tree.itemClicked.connect(self._on_item_click)

    def _analyze(self) -> None:
        report = dashboard.generate_report()
        self._tree.clear()
        for h in report.health:
            n_issues = len(h.issues) + len(h.warnings)
            item = QTreeWidgetItem([
                f"{h.status_icon} {h.name}",
                f"{h.score}/100",
                str(n_issues) if n_issues else "OK",
            ])
            item.setData(0, Qt.UserRole, h)
            self._tree.addTopLevelItem(item)

        stats = report.usage_stats
        self._summary.setText(
            f"<b>{report.total_projects}</b> projets — "
            f"<b>{stats['healthy_count']}</b> sains — "
            f"<b>{stats['broken_count']}</b> problematiques — "
            f"rapport du {report.generated_at}"
        )

    def _on_item_click(self, item, _col) -> None:
        h = item.data(0, Qt.UserRole)
        if not h:
            return
        lines = list(h.issues) + list(h.warnings) + list(h.info)
        lines.append(f"Commits : {h.commit_count}  /  Derniere ouverture : {h.last_opened}")
        self._detail.setPlainText("\n".join(lines))


