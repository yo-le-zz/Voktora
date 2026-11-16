"""Onglet « Groupe & configuration » de la synchronisation (1.1.4) : état + Pause/Reprendre/Stop, Push config,
configurations reçues (aperçu avant application), mode du groupe (égalitaire / dirigé par un chef)."""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

STATE_COLORS = {"stopped": "#6c7086", "running": "#1a7f37", "paused": "#9a6700", "blocked": "#cf222e"}


class _Done(QObject):
    done = Signal(str)


class SyncGroupPanel(QWidget):
    def __init__(self, svc, parent=None):
        super().__init__(parent)
        self.svc = svc
        self._done = _Done()
        self._done.done.connect(self._report)
        lay = QVBoxLayout(self)

        self.state = QLabel("")
        self.state.setStyleSheet("font-weight:600;padding:4px")
        lay.addWidget(self.state)
        row = QHBoxLayout()
        self.pause_btn = QPushButton("⏸ Pause")
        self.stop_btn = QPushButton("⏹ Stop")
        self.pause_btn.clicked.connect(self._toggle_pause)
        self.stop_btn.clicked.connect(self._stop)
        row.addWidget(self.pause_btn)
        row.addWidget(self.stop_btn)
        self.start_btn = QPushButton("▶ Démarrer")
        self.start_btn.clicked.connect(self._start)
        row.addWidget(self.start_btn)
        row.addStretch()
        lay.addLayout(row)
        self.gate = QLabel("")
        self.gate.setWordWrap(True)
        lay.addWidget(self.gate)

        cfg = QGroupBox("Configuration complète (thèmes, icônes, styles, plugins, profils…)")
        c = QVBoxLayout(cfg)
        hint = QLabel("« Push config » envoie TOUTE la configuration non sensible à vos autres PC (jamais le coffre ni les jetons). "
                      "La synchronisation des projets reste bloquée tant que les configurations diffèrent : c'est ce qui évite les conflits.")
        hint.setWordWrap(True)
        c.addWidget(hint)
        push_row = QHBoxLayout()
        self.push_btn = QPushButton("⬆ Push config")
        self.push_btn.clicked.connect(self._push)
        self.pull_btn = QPushButton("⬇ Récupérer la config du groupe")
        self.pull_btn.clicked.connect(self._pull)
        push_row.addWidget(self.push_btn)
        push_row.addWidget(self.pull_btn)
        push_row.addStretch()
        c.addLayout(push_row)
        c.addWidget(QLabel("Configurations reçues :"))
        self.inbox = QListWidget()
        self.inbox.setMaximumHeight(90)
        c.addWidget(self.inbox)
        inbox_row = QHBoxLayout()
        self.preview_btn = QPushButton("Aperçu des différences")
        self.apply_btn = QPushButton("Appliquer")
        self.discard_btn = QPushButton("Ignorer")
        self.preview_btn.clicked.connect(self._preview)
        self.apply_btn.clicked.connect(self._apply)
        self.discard_btn.clicked.connect(self._discard)
        for b in (self.preview_btn, self.apply_btn, self.discard_btn):
            inbox_row.addWidget(b)
        inbox_row.addStretch()
        c.addLayout(inbox_row)
        self.diff = QPlainTextEdit()
        self.diff.setReadOnly(True)
        self.diff.setMaximumHeight(130)
        c.addWidget(self.diff)
        lay.addWidget(cfg)

        grp = QGroupBox("Rôles du groupe")
        g = QVBoxLayout(grp)
        self.mode = QComboBox()
        self.mode.addItem("Égalitaire — le PC principal gagne les conflits", "egalitarian")
        self.mode.addItem("Dirigé — un PC chef est la source de vérité", "directed")
        self.leader = QComboBox()
        g_row = QHBoxLayout()
        g_row.addWidget(self.mode)
        g_row.addWidget(self.leader)
        apply_mode = QPushButton("Appliquer")
        apply_mode.clicked.connect(self._set_mode)
        abdicate = QPushButton("Abdiquer")
        abdicate.clicked.connect(self._abdicate)
        g_row.addWidget(apply_mode)
        g_row.addWidget(abdicate)
        g.addLayout(g_row)
        self.roles = QLabel("")
        self.roles.setWordWrap(True)
        g.addWidget(self.roles)
        self.proposals = QListWidget()
        self.proposals.setMaximumHeight(60)
        g.addWidget(self.proposals)
        prop_row = QHBoxLayout()
        accept = QPushButton("Accepter la proposition")
        decline = QPushButton("Refuser")
        accept.clicked.connect(self._accept_proposal)
        decline.clicked.connect(self._decline_proposal)
        prop_row.addWidget(accept)
        prop_row.addWidget(decline)
        prop_row.addStretch()
        g.addLayout(prop_row)
        lay.addWidget(grp)
        lay.addStretch()

    # ── affichage ────────────────────────────────────────────────────────────
    def refresh(self, snap: dict) -> None:
        ctl = snap.get("control", {})
        state = ctl.get("state", "stopped")
        self.state.setText(f"{ctl.get('icon', '')} État : {ctl.get('label', '')}")
        self.state.setStyleSheet(f"font-weight:600;padding:4px;color:{STATE_COLORS.get(state, '#6c7086')}")
        self.pause_btn.setText("▶ Reprendre" if ctl.get("paused") else "⏸ Pause")
        self.pause_btn.setEnabled(state != "stopped")
        self.stop_btn.setEnabled(state != "stopped")
        self.start_btn.setEnabled(state == "stopped")
        blocked = ctl.get("blocked") or {}
        self.gate.setText("⛔ " + " · ".join(blocked.values()) + "  → utilisez « Push config » ou appliquez la configuration du groupe." if blocked else "")
        conf = snap.get("config", {})
        self._fill(self.inbox, [(f"{i['name']} — révision {i['rev'][:8]}, {i['files']} fichier(s)", i["from"]) for i in conf.get("inbox", [])])
        self._fill(self.proposals, [(f"{p['name']} propose : {p['mode']}" + (f" (chef : {p['leader']})" if p["leader"] else ""), p["id"])
                                    for p in conf.get("proposals", [])])
        group = snap.get("group", {})
        peers = [(self.svc.settings["device_name"] + " (ce PC)", self.svc.settings.device_id)] + [(p["name"], p["id"]) for p in self.svc.settings["peers"]]
        if self.leader.count() != len(peers):
            self.leader.clear()
            for name, pid in peers:
                self.leader.addItem(name, pid)
        names = dict((pid, name) for name, pid in peers)
        roles = snap.get("roles", {})
        label = {"leader": "chef", "follower": "suiveur", "primary": "principal", "secondary": "secondaire", "peer": "égal"}
        mode = "Dirigé" if group.get("mode") == "directed" else "Égalitaire"
        self.roles.setText(f"Mode actuel : {mode} (époque {group.get('epoch', 0)}) — " + ", ".join(
            f"{names.get(pid, pid)} : {label.get(r, r)}" for pid, r in roles.items()))

    @staticmethod
    def _fill(widget: QListWidget, items: list[tuple[str, str]]) -> None:
        current = widget.currentItem().data(256) if widget.currentItem() else None
        widget.clear()
        for text, key in items:
            widget.addItem(text)
            widget.item(widget.count() - 1).setData(256, key)
            if key == current:
                widget.setCurrentRow(widget.count() - 1)

    def _selected(self, widget: QListWidget) -> str:
        item = widget.currentItem()
        return item.data(256) if item else ""

    # ── actions ──────────────────────────────────────────────────────────────
    def _run(self, work, ok: str) -> None:
        def go() -> None:
            try:
                work()
                self._done.done.emit(ok)
            except Exception as exc:  # noqa: BLE001
                self._done.done.emit("Erreur : " + str(exc))
        threading.Thread(target=go, daemon=True, name="voktora-sync-ui").start()

    def _report(self, message: str) -> None:
        self.gate.setText(message)

    def _toggle_pause(self) -> None:
        (self.svc.resume if self.svc.control.paused else self.svc.pause)()

    def _stop(self) -> None:
        self._run(self.svc.stop, "Synchronisation arrêtée.")

    def _start(self) -> None:
        self._run(self.svc.start, "Synchronisation démarrée.")

    def _push(self) -> None:
        if QMessageBox.question(self, "Push config", "Envoyer toute votre configuration aux autres PC ?") == QMessageBox.Yes:
            self._run(self.svc.push_config, "Push config envoyé.")

    def _pull(self) -> None:
        for peer in self.svc.settings["peers"]:
            self._run(lambda pid=peer["id"]: self.svc.fetch_group_config(pid), "Configuration du groupe demandée.")
            break

    def _preview(self) -> None:
        pid = self._selected(self.inbox)
        if not pid:
            return
        try:
            diff = self.svc.config_preview(pid)
            self.diff.setPlainText(diff.summary() + "\n" + "\n".join(diff.lines()))
        except Exception as exc:  # noqa: BLE001
            self.diff.setPlainText("Erreur : " + str(exc))

    def _apply(self) -> None:
        pid = self._selected(self.inbox)
        if not pid:
            return
        self._preview()
        if QMessageBox.question(self, "Appliquer la configuration",
                                "Appliquer cette configuration ? Une sauvegarde est faite et restaurée automatiquement en cas d'échec.") != QMessageBox.Yes:
            return
        try:
            result = self.svc.apply_received_config(pid)
            self.gate.setText(f"Configuration appliquée ({result.changes} changement(s))." if result.ok else "Refusée : " + result.error)
        except Exception as exc:  # noqa: BLE001
            self.gate.setText("Erreur : " + str(exc))

    def _discard(self) -> None:
        pid = self._selected(self.inbox)
        if pid:
            self.svc.cfg.discard(pid)

    def _set_mode(self) -> None:
        mode, leader = self.mode.currentData(), self.leader.currentData()
        self._run(lambda: self.svc.set_group_mode(mode, leader if mode == "directed" else ""), "Mode envoyé (accord des autres PC requis s'ils dirigent).")

    def _abdicate(self) -> None:
        self._run(self.svc.abdicate, "Abdication envoyée.")

    def _accept_proposal(self) -> None:
        pid = self._selected(self.proposals)
        if pid:
            self._run(lambda: self.svc.groups.accept(pid), "Accord envoyé.")

    def _decline_proposal(self) -> None:
        pid = self._selected(self.proposals)
        if pid:
            self.svc.groups.decline(pid)
