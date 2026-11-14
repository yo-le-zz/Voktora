"""Moniteur développeur global : choix du mode, ouverture de la fenêtre détachée (processus séparé)."""

from __future__ import annotations

import devmon
from devmon import core as dm
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QMessageBox,
    QVBoxLayout,
)


class DevMonitorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Moniteur développeur global")
        self.setMinimumWidth(520)
        prefs = dm.read_prefs()
        lay = QVBoxLayout(self)
        intro = QLabel("Ouvre une seconde fenêtre, dans un processus séparé : elle ne bloque pas Voktora et reste ouverte "
                       "même si Voktora plante. Elle affiche en direct plantages, erreurs, journaux, clics et blocages de l'interface.\n"
                       "Jamais le texte tapé ni le contenu des champs ; jetons et mots de passe masqués ; tout reste sur cet ordinateur.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        form = QFormLayout()
        self.mode = QComboBox()
        from devmon import emitter
        live = emitter.current()
        for key in dm.LEVELS:
            self.mode.addItem(dm.LABELS[key], key)
        self.mode.setCurrentIndex(dm.RANK[live.level if live else dm.valid_level(prefs.get("mode"))])
        self.autostart = QCheckBox("Ouvrir automatiquement au démarrage de Voktora")
        self.autostart.setChecked(bool(prefs.get("autostart")))
        form.addRow("Mode :", self.mode)
        form.addRow("", self.autostart)
        lay.addLayout(form)
        self.state = QLabel("Observation active dans cette session." if live else "Observation inactive dans cette session.")
        lay.addWidget(self.state)
        buttons = QDialogButtonBox()
        self.open_btn = buttons.addButton("Ouvrir le moniteur", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("Fermer", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self._open)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _open(self) -> None:
        level = self.mode.currentData()
        dm.write_prefs({**dm.read_prefs(), "mode": level, "autostart": self.autostart.isChecked()})
        try:
            em = devmon.open_monitor(level)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Moniteur développeur", f"Impossible de démarrer le moniteur : {exc}")
            return
        self.state.setText(f"Observation active — mode {em.level}. Journal : {em.session}")
