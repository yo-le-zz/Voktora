"""
Voktora — ui_main.diagnostic_dialog
Fragment de ui_main.py extrait lors du découpage v1.0.2 en package.
"""

from __future__ import annotations

import html

import core
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from . import workers


class DiagnosticDialog(QDialog):
    def __init__(self, result: core.HealthCheckResult, parent: QWidget | None = None):
        super().__init__(parent)
        self._result = result
        self.setWindowTitle("🔍  Diagnostic — Voktora")
        self.setMinimumWidth(620)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        has_errors = result.has_errors
        color      = "#f38ba8" if has_errors else "#fab387"
        icon_str   = "⛔" if has_errors else "⚠"

        title = QLabel(f"{icon_str}  Problèmes détectés au démarrage")
        title.setStyleSheet(f"font-size: 17px; font-weight: 700; color: {color};")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        sub = QLabel(
            "Voktora a détecté des anomalies. "
            "Cliquez sur « Réparer » pour tenter une correction automatique."
        )
        sub.setWordWrap(True)
        sub.setStyleSheet("color: #a6adc8; font-size: 12px;")
        layout.addWidget(sub)
        layout.addWidget(workers._make_sep())

        scroll  = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        vbox    = QVBoxLayout(content)
        vbox.setSpacing(10)
        vbox.setContentsMargins(0, 0, 0, 0)

        self._fix_buttons: list[tuple[QPushButton, QLabel, core.DiagnosticIssue]] = []

        for issue in result.issues:
            card = QFrame()
            card.setStyleSheet(
                "QFrame { background-color: #181825; border: 1px solid "
                + ("#f38ba8" if issue.level == "error" else "#fab387")
                + "; border-radius: 8px; padding: 10px; }"
            )
            cv = QVBoxLayout(card)
            cv.setSpacing(6)

            lbl_title = QLabel(
                f"{'⛔' if issue.level == 'error' else '⚠'}"
                f"  <b>{html.escape(issue.title)}</b>"
                f"  <span style='color:#6c7086; font-size:11px'>[{issue.category}]</span>"
            )
            lbl_title.setTextFormat(Qt.RichText)
            cv.addWidget(lbl_title)

            lbl_detail = QLabel(html.escape(issue.detail).replace("\n", "<br>"))
            lbl_detail.setWordWrap(True)
            lbl_detail.setStyleSheet("color: #a6adc8; font-size: 12px;")
            lbl_detail.setTextFormat(Qt.RichText)
            cv.addWidget(lbl_detail)

            if issue.can_fix:
                row = QHBoxLayout()
                btn_fix = QPushButton(f"🔧  {issue.fix_label}")
                btn_fix.setObjectName("warn")
                btn_fix.setFixedWidth(260)
                lbl_status = QLabel("")
                lbl_status.setStyleSheet("font-size: 12px; color: #a6e3a1;")
                row.addWidget(btn_fix)
                row.addWidget(lbl_status)
                row.addStretch()
                cv.addLayout(row)
                self._fix_buttons.append((btn_fix, lbl_status, issue))
                btn_fix.clicked.connect(
                    lambda checked=False, b=btn_fix, lb=lbl_status, iss=issue:
                        self._run_fix(b, lb, iss)
                )

            vbox.addWidget(card)

        vbox.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll)
        layout.addWidget(workers._make_sep())

        btns = QHBoxLayout()
        btn_ignore = QPushButton("Ignorer et continuer")
        btn_ignore.setObjectName("subtle")
        btn_ignore.clicked.connect(self.accept)
        btns.addStretch()
        btns.addWidget(btn_ignore)
        layout.addLayout(btns)

    def _run_fix(self, btn, lbl, issue):
        btn.setEnabled(False)
        lbl.setText("⏳  Réparation en cours…")
        lbl.setStyleSheet("color: #fab387; font-size: 12px;")
        QApplication.processEvents()

        success, msg = False, "Réparation non implémentée."

        if issue.category == "config":
            success, msg = core.repair_config()
        elif issue.category == "data":
            success, msg = core.repair_orphans()
        elif issue.category == "dependency":
            success, msg = core.reinstall_dependencies()

        if success:
            lbl.setText(f"✅  {msg[:80]}")
            lbl.setStyleSheet("color: #a6e3a1; font-size: 12px;")
            btn.setText("✅  Réparé")
        else:
            lbl.setText(f"❌  Échec : {msg[:120]}")
            lbl.setStyleSheet("color: #f38ba8; font-size: 12px;")
            btn.setEnabled(True)
            btn.setText("↺  Réessayer")


# ══════════════════════════════════════════════════════
#  DIALOG DÉSINSTALLATION
# ══════════════════════════════════════════════════════

