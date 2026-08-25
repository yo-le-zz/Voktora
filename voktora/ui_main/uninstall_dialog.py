"""
Voktora — ui_main.uninstall_dialog
Fragment de ui_main.py extrait lors du découpage v1.0.2 en package.
"""

from __future__ import annotations

from pathlib import Path

import core
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import workers


class UninstallDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Désinstaller Voktora")
        self.setFixedWidth(560)
        self.setModal(True)

        self._backup_dir: Path | None = None
        self._do_backup: bool = False

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(28, 28, 28, 28)
        self._layout.setSpacing(0)

        self._pages: list[QWidget] = []
        self._current_page = 0

        for page in [self._build_page1(), self._build_page2(), self._build_page3()]:
            self._layout.addWidget(page)
            self._pages.append(page)

        self._show_page(0)

    def _build_page1(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(16)
        lbl_title = QLabel("⚠  Désinstaller Voktora")
        lbl_title.setStyleSheet("font-size: 18px; font-weight: 700; color: #f38ba8;")
        lbl_title.setAlignment(Qt.AlignCenter)
        v.addWidget(lbl_title)
        v.addWidget(workers._make_sep())
        warn_box = QLabel(
            "<b>Les éléments suivants seront supprimés définitivement :</b><br><br>"
            "• Le dossier entier de l'application Voktora<br>"
            "• Les fichiers de configuration (<code>data/config.json</code>)<br>"
            "• Les backups automatiques (<code>data/backups/</code>)<br>"
            "• Les assets de l'application (<code>assets/</code>)<br><br>"
            "<b>Les instances et intents sur vos disques externes ne sont PAS supprimés</b><br>"
            "sauf si vous les avez stockés dans le dossier de l'application.<br><br>"
            "<span style='color:#f38ba8;'>⚠  Assurez-vous d'avoir fait des backups avant de continuer.</span>"
        )
        warn_box.setWordWrap(True)
        warn_box.setStyleSheet(
            "background-color: #11111b; border: 1px solid #f38ba8;"
            "border-radius: 8px; padding: 14px; color: #cdd6f4; line-height: 1.6;"
        )
        v.addWidget(warn_box)
        v.addSpacing(12)
        btns = QHBoxLayout()
        btn_cancel = QPushButton("✕  Annuler — Garder Voktora")
        btn_cancel.setObjectName("primary")
        btn_cancel.clicked.connect(self.reject)
        btn_next = QPushButton("Continuer →")
        btn_next.setObjectName("danger")
        btn_next.clicked.connect(lambda: self._show_page(1))
        btns.addWidget(btn_cancel)
        btns.addStretch()
        btns.addWidget(btn_next)
        v.addLayout(btns)
        return w

    def _build_page2(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(16)
        lbl_title = QLabel("💾  Sauvegarder avant de partir ?")
        lbl_title.setStyleSheet("font-size: 16px; font-weight: 700; color: #fab387;")
        lbl_title.setAlignment(Qt.AlignCenter)
        v.addWidget(lbl_title)
        v.addWidget(workers._make_sep())
        info = QLabel(
            "Voktora peut exporter <b>toutes vos instances et intents</b> en .zip<br>"
            "et déplacer vos backups existants vers un dossier de votre choix.<br><br>"
            "Cette étape est <b>facultative</b> mais fortement recommandée."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #cdd6f4; line-height: 1.6;")
        v.addWidget(info)
        self.chk_backup = QCheckBox("✔  Oui, exporter mes données vers un dossier de sauvegarde")
        self.chk_backup.setChecked(True)
        self.chk_backup.setStyleSheet("font-weight: 600; color: #a6e3a1;")
        v.addWidget(self.chk_backup)
        dir_row = QHBoxLayout()
        self.lbl_backup_dir = QLabel("(aucun dossier sélectionné)")
        self.lbl_backup_dir.setObjectName("pathLabel")
        self.lbl_backup_dir.setWordWrap(True)
        self.lbl_backup_dir.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        btn_choose = QPushButton("📂  Choisir…")
        btn_choose.setFixedWidth(110)
        btn_choose.clicked.connect(self._choose_backup_dir)
        dir_row.addWidget(self.lbl_backup_dir)
        dir_row.addWidget(btn_choose)
        v.addLayout(dir_row)
        self.chk_backup.toggled.connect(lambda checked: btn_choose.setEnabled(checked))
        v.addSpacing(8)
        v.addWidget(workers._make_sep())
        btns = QHBoxLayout()
        btn_back = QPushButton("← Retour")
        btn_back.setObjectName("subtle")
        btn_back.clicked.connect(lambda: self._show_page(0))
        btn_next = QPushButton("Continuer →")
        btn_next.setObjectName("warn")
        btn_next.clicked.connect(self._validate_page2)
        btns.addWidget(btn_back)
        btns.addStretch()
        btns.addWidget(btn_next)
        v.addLayout(btns)
        return w

    def _build_page3(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(16)
        lbl_title = QLabel("🗑  Confirmation finale")
        lbl_title.setStyleSheet("font-size: 16px; font-weight: 700; color: #f38ba8;")
        lbl_title.setAlignment(Qt.AlignCenter)
        v.addWidget(lbl_title)
        v.addWidget(workers._make_sep())
        self.lbl_summary = QLabel()
        self.lbl_summary.setWordWrap(True)
        self.lbl_summary.setStyleSheet(
            "background-color: #11111b; border: 1px solid #313244;"
            "border-radius: 8px; padding: 14px; color: #cdd6f4; line-height: 1.6;"
        )
        v.addWidget(self.lbl_summary)
        v.addSpacing(8)
        btns = QHBoxLayout()
        btn_back    = QPushButton("← Retour")
        btn_back.setObjectName("subtle")
        btn_back.clicked.connect(lambda: self._show_page(1))
        btn_cancel  = QPushButton("Annuler")
        btn_cancel.clicked.connect(self.reject)
        btn_confirm = QPushButton("🗑  Confirmer la désinstallation")
        btn_confirm.setObjectName("danger")
        btn_confirm.clicked.connect(self.accept)
        btns.addWidget(btn_back)
        btns.addWidget(btn_cancel)
        btns.addStretch()
        btns.addWidget(btn_confirm)
        v.addLayout(btns)
        return w

    def _show_page(self, index: int):
        for i, p in enumerate(self._pages):
            p.setVisible(i == index)
        self._current_page = index
        self.adjustSize()

    def _choose_backup_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "Choisir le dossier de sauvegarde")
        if folder:
            self._backup_dir = Path(folder)
            self.lbl_backup_dir.setText(str(self._backup_dir))

    def _validate_page2(self):
        self._do_backup = self.chk_backup.isChecked()
        if self._do_backup and self._backup_dir is None:
            QMessageBox.warning(self, "Voktora",
                "Veuillez choisir un dossier de sauvegarde,\nou décochez l'option de backup.")
            return
        lines: list[str] = []
        if self._do_backup and self._backup_dir:
            lines.append(
                f"✅  Backup de toutes les instances et intents vers :<br>"
                f"<code>{self._backup_dir}</code>"
            )
        else:
            lines.append("⚠  <b>Aucun backup</b> ne sera effectué.")
        lines.append(
            f"<br>🗑  Suppression du dossier de l'application :<br>"
            f"<code>{core.get_app_dir()}</code>"
        )
        lines.append(
            "<br>Voktora se fermera immédiatement après avoir lancé le script de nettoyage."
        )
        self.lbl_summary.setText("<br>".join(lines))
        self._show_page(2)

    def get_options(self) -> tuple[bool, Path | None]:
        return self._do_backup, self._backup_dir


# ══════════════════════════════════════════════════════
#  DIALOG GITHUB (configuration instance)
# ══════════════════════════════════════════════════════

