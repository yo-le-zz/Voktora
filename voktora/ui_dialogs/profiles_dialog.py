"""
Voktora — ui_dialogs.profiles_dialog
Fragment de ui_dialogs.py extrait lors du découpage v1.0.2 en package.
"""

from __future__ import annotations

from pathlib import Path

import profiles
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

# ════════════════════════════════════════════════════════════════════════════
# PROFILES UI
# ════════════════════════════════════════════════════════════════════════════

class ProfilesDialog(QDialog):
    """Gestion des profils d'execution d'un projet."""

    def __init__(self, project_path: Path, parent=None):
        super().__init__(parent)
        self._project_path = project_path
        self.setWindowTitle(f"Profils — {project_path.name}")
        self.setMinimumSize(520, 480)

        v = QVBoxLayout(self)
        v.setSpacing(10)
        v.setContentsMargins(14, 12, 14, 12)

        v.addWidget(QLabel(f"<b>Profils d'execution</b> — {project_path.name}",
                           styleSheet="color:#cdd6f4;"))

        self._list = QListWidget()
        self._list.setMaximumHeight(120)
        self._list.currentRowChanged.connect(self._on_select)
        v.addWidget(self._list)

        form = QFormLayout()
        form.setSpacing(8)
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Mon profil")
        self._cmd_edit  = QLineEdit()
        self._cmd_edit.setPlaceholderText("python src/main.py")
        self._dir_edit  = QLineEdit()
        self._dir_edit.setPlaceholderText("(racine du projet)")
        self._env_edit  = QTextEdit()
        self._env_edit.setFixedHeight(70)
        self._env_edit.setPlaceholderText("VARIABLE=valeur\nAUTRE=valeur2")
        self._pre_edit  = QTextEdit()
        self._pre_edit.setFixedHeight(50)
        self._pre_edit.setPlaceholderText("cmd pre-run (une par ligne)")
        self._post_edit = QTextEdit()
        self._post_edit.setFixedHeight(50)
        self._post_edit.setPlaceholderText("cmd post-run (une par ligne)")
        self._default_chk = QCheckBox("Profil par defaut")

        form.addRow("Nom :", self._name_edit)
        form.addRow("Commande :", self._cmd_edit)
        form.addRow("Dossier :", self._dir_edit)
        form.addRow("Env vars :", self._env_edit)
        form.addRow("Pre-run :", self._pre_edit)
        form.addRow("Post-run :", self._post_edit)
        form.addRow("", self._default_chk)
        v.addLayout(form)

        row = QHBoxLayout()
        for label, slot in [
            ("Nouveau", self._new),
            ("Sauvegarder", self._save),
            ("Supprimer", self._delete),
            ("Lancer", self._run),
        ]:
            b = QPushButton(label)
            if label == "Sauvegarder":
                b.setObjectName("primary")
            b.clicked.connect(slot)
            row.addWidget(b)
        btn_close = QPushButton("Fermer")
        btn_close.clicked.connect(self.accept)
        row.addStretch()
        row.addWidget(btn_close)
        v.addLayout(row)

        self._refresh()

    def _refresh(self) -> None:
        self._list.clear()
        for p in profiles.load_profiles(self._project_path):
            self._list.addItem(f"{'* ' if p.default else ''}{p.name}  —  {p.run_cmd}")

    def _on_select(self, row: int) -> None:
        all_p = profiles.load_profiles(self._project_path)
        if 0 <= row < len(all_p):
            p = all_p[row]
            self._name_edit.setText(p.name)
            self._cmd_edit.setText(p.run_cmd)
            self._dir_edit.setText(p.work_dir)
            self._env_edit.setPlainText("\n".join(f"{k}={v}" for k, v in p.env.items()))
            self._pre_edit.setPlainText("\n".join(p.pre_run))
            self._post_edit.setPlainText("\n".join(p.post_run))
            self._default_chk.setChecked(p.default)

    def _parse_env(self) -> dict:
        out = {}
        for line in self._env_edit.toPlainText().splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                out[k.strip()] = v.strip()
        return out

    def _save(self) -> None:
        name = self._name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Erreur", "Le nom est requis.")
            return
        all_p = profiles.load_profiles(self._project_path)
        pr = profiles.RunProfile(
            name      = name,
            run_cmd   = self._cmd_edit.text().strip(),
            work_dir  = self._dir_edit.text().strip(),
            env       = self._parse_env(),
            pre_run   = [ln for ln in self._pre_edit.toPlainText().splitlines() if ln.strip()],
            post_run  = [ln for ln in self._post_edit.toPlainText().splitlines() if ln.strip()],
            default   = self._default_chk.isChecked(),
        )
        idx = next((i for i, p in enumerate(all_p) if p.name == name), -1)
        if idx >= 0:
            all_p[idx] = pr
        else:
            all_p.append(pr)
        if pr.default:
            for i, p in enumerate(all_p):
                if p.name != name:
                    all_p[i].default = False
        profiles.save_profiles(self._project_path, all_p)
        self._refresh()

    def _new(self) -> None:
        for w in (self._name_edit, self._cmd_edit, self._dir_edit,
                  self._env_edit, self._pre_edit, self._post_edit):
            if hasattr(w, "clear"):
                w.clear()
        self._default_chk.setChecked(False)
        self._name_edit.setFocus()

    def _delete(self) -> None:
        row = self._list.currentRow()
        all_p = profiles.load_profiles(self._project_path)
        if 0 <= row < len(all_p):
            profiles.delete_profile(self._project_path, all_p[row].name)
            self._refresh()

    def _run(self) -> None:
        row = self._list.currentRow()
        all_p = profiles.load_profiles(self._project_path)
        if 0 <= row < len(all_p):
            proc = profiles.launch(self._project_path, all_p[row])
            if proc:
                QMessageBox.information(self, "Lance",
                    f"Profil '{all_p[row].name}' lance (PID {proc.pid}).")


