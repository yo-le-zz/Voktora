"""
Voktora — ui_dialogs.ai_chat_dialog (1.1.0)
Chat IA intégré : discussion avec le fournisseur actif, qui peut utiliser les outils de Voktora selon les permissions
réglées ici (désactivé / demander / automatique). Les actions qui modifient demandent toujours confirmation.
"""

from __future__ import annotations

import html
import threading

import ai_agent
import ai_providers
import core
import markdown_lite
from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QKeyEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

LEVEL_LABELS = {ai_agent.OFF: "Désactivé", ai_agent.ASK: "Demander à chaque fois", ai_agent.AUTO: "Automatique"}


class PermissionsDialog(QDialog):
    """Une ligne par permission : ce que l'IA a le droit de faire."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Permissions de l'assistant IA")
        self.setMinimumWidth(560)
        v = QVBoxLayout(self)
        intro = QLabel("L'assistant n'a accès qu'à ce que vous autorisez. Les actions qui modifient quelque chose "
                       "demandent toujours votre confirmation (jamais « automatique »).")
        intro.setWordWrap(True)
        v.addWidget(intro)
        self._boxes: dict[str, QComboBox] = {}
        levels = ai_agent.permission_levels()
        for pid, perm in ai_agent.PERMISSIONS.items():
            row = QHBoxLayout()
            text = QLabel(f"<b>{html.escape(perm.label)}</b><br><span style='color:#7f849c'>{html.escape(perm.description)}</span>")
            text.setWordWrap(True)
            box = QComboBox()
            for level in ai_agent.LEVELS:
                if level == ai_agent.AUTO and perm.writes:
                    continue
                box.addItem(LEVEL_LABELS[level], level)
            box.setCurrentIndex(max(0, box.findData(levels[pid])))
            self._boxes[pid] = box
            row.addWidget(text, 1)
            row.addWidget(box)
            v.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)

    def _save(self) -> None:
        for pid, box in self._boxes.items():
            ai_agent.set_permission(pid, box.currentData())
        self.accept()


class _Bridge(QObject):
    """Relie le fil de travail (réseau, outils) à l'interface : tout passe par des signaux."""
    line = Signal(str, str)                 # genre, texte
    confirm = Signal(str, str)
    finished = Signal(str)


class _Composer(QPlainTextEdit):
    """Zone de saisie : Entrée envoie, Maj+Entrée ajoute une ligne."""
    submitted = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not event.modifiers() & Qt.ShiftModifier:
            self.submitted.emit()
            return
        super().keyPressEvent(event)


# genre → (étiquette, couleur)
_STYLE = {"user": ("Vous", "#89b4fa"), "assistant": ("Assistant", "#a6e3a1"), "tool": ("outil", "#f9e2af"),
          "result": ("résultat", "#7f849c"), "denied": ("refusé", "#f38ba8"), "error": ("erreur", "#f38ba8"),
          "info": ("", "#7f849c")}
RENDER_INTERVAL_MS = 60                     # le flux ne redessine pas à chaque jeton


class AIChatDialog(QDialog):
    def __init__(self, parent=None, generate=None):
        super().__init__(parent)
        self.setWindowTitle("Assistant IA")
        self.setMinimumSize(720, 620)
        self._generate = generate
        self._agent: ai_agent.Agent | None = None
        self._busy = False
        self._cancel = threading.Event()
        self._answer = threading.Event()
        self._allowed = False
        self._messages: list[list[str]] = []        # [genre, texte]
        self._streaming = False                     # le dernier message « assistant » est en cours d'écriture
        self._bridge = _Bridge()
        self._bridge.line.connect(self._on_event)
        self._bridge.confirm.connect(self._ask_confirmation)
        self._bridge.finished.connect(self._done)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(RENDER_INTERVAL_MS)
        self._timer.timeout.connect(self._render)

        v = QVBoxLayout(self)
        top = QHBoxLayout()
        self.provider = QComboBox()
        self.provider.currentIndexChanged.connect(lambda _: setattr(self, "_agent", None))
        perms = QPushButton("Permissions…")
        perms.clicked.connect(self._permissions)
        clear = QPushButton("Nouvelle discussion")
        clear.clicked.connect(self._reset)
        top.addWidget(QLabel("Fournisseur :"))
        top.addWidget(self.provider, 1)
        top.addWidget(perms)
        top.addWidget(clear)
        v.addLayout(top)
        self.view = QTextBrowser()
        self.view.setOpenLinks(False)
        self.view.anchorClicked.connect(lambda url: QDesktopServices.openUrl(QUrl(url)))
        self.view.document().setDefaultStyleSheet("p, li { line-height: 135%; }")
        v.addWidget(self.view, 1)
        self.status = QLabel("")
        self.status.setStyleSheet("color:#7f849c")
        v.addWidget(self.status)
        bottom = QHBoxLayout()
        self.edit = _Composer()
        self.edit.setFixedHeight(64)
        self.edit.setPlaceholderText("Demandez quelque chose… (Entrée envoie, Maj+Entrée = nouvelle ligne)")
        self.edit.submitted.connect(self._send)
        self.send = QPushButton("Envoyer")
        self.send.clicked.connect(self._send)
        self.stop = QPushButton("Arrêter")
        self.stop.setEnabled(False)
        self.stop.clicked.connect(self._cancel.set)
        bottom.addWidget(self.edit, 1)
        bottom.addWidget(self.send)
        bottom.addWidget(self.stop)
        v.addLayout(bottom)
        self._load_providers()
        self._add("info", "Bonjour ! Je peux utiliser les outils de Voktora selon vos permissions (bouton « Permissions »).")

    # ── fournisseurs ──
    def _load_providers(self) -> None:
        ai = core.get_ai_config()
        for p in ai["providers"]:
            self.provider.addItem(f"{p['name']} — {p.get('model') or '?'}", p)
        index = next((i for i, p in enumerate(ai["providers"]) if p["id"] == ai["active"]), 0)
        self.provider.setCurrentIndex(index)
        if not ai["providers"]:
            self._add("error", "Aucun fournisseur IA configuré : ajoutez-en un dans Configuration → IA (Ollama, OmniRoute…).")
            self.send.setEnabled(False)

    # ── affichage ──
    def _add(self, kind: str, text: str) -> None:
        self._messages.append([kind, text])
        self._schedule()

    def _schedule(self) -> None:
        if not self._timer.isActive():
            self._timer.start()

    def _render(self) -> None:
        parts: list[str] = []
        last = len(self._messages) - 1
        for index, (kind, text) in enumerate(self._messages):
            label, color = _STYLE[kind]
            if kind == "assistant":
                body = markdown_lite.render(text)
                if self._streaming and index == last:
                    body += f"<span style='color:{color}'>▍</span>"
                parts.append(f"<div style='margin:10px 0 2px 0'><b style='color:{color}'>{label}</b></div>{body}")
            elif kind == "user":
                parts.append(f"<div style='margin:12px 0 2px 0'><b style='color:{color}'>{label}</b></div>"
                             f"<p style='margin:2px 0'>{html.escape(text).replace(chr(10), '<br>')}</p>")
            elif kind in ("tool", "result"):
                parts.append(f"<div style='color:{color};font-size:12px;margin:1px 0 1px 12px'>"
                             f"<b>{label}</b> <code>{html.escape(text[:300])}</code></div>")
            else:
                prefix = f"<b style='color:{color}'>{label}</b> " if label else ""
                parts.append(f"<p style='color:{color};margin:6px 0'>{prefix}{html.escape(text)}</p>")
        bar = self.view.verticalScrollBar()
        stick = bar.value() >= bar.maximum() - 24
        self.view.setHtml("".join(parts))
        if stick:
            bar.setValue(bar.maximum())

    def _on_event(self, kind: str, text: str) -> None:
        if kind == "token":
            if not self._streaming:
                self._messages.append(["assistant", ""])
                self._streaming = True
                self.status.setText("L'assistant écrit…")
            self._messages[-1][1] += text
            self._schedule()
            return
        self._streaming = False
        if kind == "tool":
            self.status.setText("Utilisation d'un outil…")
        self._add(kind, text)

    def _permissions(self) -> None:
        PermissionsDialog(self).exec()

    def _reset(self) -> None:
        if self._busy:
            return
        self._agent = None
        self._messages.clear()
        self._add("info", "Nouvelle discussion.")

    # ── envoi ──
    def _send(self) -> None:
        text = self.edit.toPlainText().strip()
        provider = self.provider.currentData()
        if not text or self._busy or not provider:
            return
        self.edit.clear()
        self._add("user", text)
        if self._agent is None:
            self._agent = ai_agent.Agent(provider, self._confirm_from_thread,
                                         lambda k, t: self._bridge.line.emit(k, t), self._generate,
                                         self._cancel.is_set)
        self._busy = True
        self._cancel.clear()
        self.send.setEnabled(False)
        self.stop.setEnabled(True)
        self.status.setText("L'assistant réfléchit…")
        agent = self._agent

        def work() -> None:
            try:
                answer = agent.ask(text)
            except ai_providers.AIError as exc:
                self._bridge.line.emit("error", str(exc))
                answer = ""
            except Exception as exc:  # noqa: BLE001
                self._bridge.line.emit("error", f"{type(exc).__name__}: {exc}")
                answer = ""
            self._bridge.finished.emit(answer)

        threading.Thread(target=work, daemon=True, name="voktora-ai-chat").start()

    def _done(self, answer: str) -> None:
        if answer:
            if self._streaming and self._messages and self._messages[-1][0] == "assistant":
                self._messages[-1][1] = answer                 # texte final, propre (sans <think>)
            elif not (self._messages and self._messages[-1][0] == "assistant" and self._messages[-1][1] == answer):
                self._messages.append(["assistant", answer])
        self._streaming = False
        self._busy = False
        self.status.setText("")
        self.send.setEnabled(True)
        self.stop.setEnabled(False)
        self._timer.stop()
        self._render()
        self.edit.setFocus()

    # ── confirmation (le fil de travail attend la réponse de l'utilisateur) ──
    def _confirm_from_thread(self, title: str, detail: str) -> bool:
        self._answer.clear()
        self._allowed = False
        self._bridge.confirm.emit(title, detail)
        while not self._answer.wait(0.2):
            if self._cancel.is_set():
                return False
        return self._allowed

    def _ask_confirmation(self, title: str, detail: str) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("L'assistant demande l'autorisation")
        box.setText(f"<b>{html.escape(title)}</b>")
        box.setInformativeText(detail)
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.No)
        box.button(QMessageBox.Yes).setText("Autoriser")
        box.button(QMessageBox.No).setText("Refuser")
        box.setWindowModality(Qt.WindowModal)
        self._allowed = box.exec() == QMessageBox.Yes
        self._answer.set()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._cancel.set()
        self._answer.set()
        super().closeEvent(event)
