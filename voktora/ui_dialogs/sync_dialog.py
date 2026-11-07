"""
Voktora — ui_dialogs.sync_dialog
Synchronisation entre PC : appareils (appairage, PC principal), contenu à synchroniser, automatisme, et état en
pourcentage de chaque PC. Contient aussi `SyncBridge` (pont thread → Qt) et `ask_source` (« à partir de quelle
source synchroniser ? »).
"""

from __future__ import annotations

import time

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from sync import get_service
from sync.settings import CATEGORIES, DEFAULT_PORT

STATE_LABEL = {"offline": "⚪ hors ligne", "online": "🟢 connecté", "syncing": "🔄 synchronisation",
               "done": "✅ à jour", "decision": "❓ choix requis", "paused": "⏸ en pause (reprise auto)",
               "error": "⚠️ erreur", "idle": "—"}


class SyncBridge(QObject):
    """Reçoit les statuts depuis les threads de synchronisation et les relaie dans le thread Qt."""
    changed = Signal(dict)

    def __init__(self, service=None):
        super().__init__()
        self.service = service or get_service()
        self.service.add_listener(self.changed.emit)


def ask_source(parent, peer_name: str, summary: str) -> str:
    """'local' | 'remote' | 'primary' | '' (annulé)."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Question)
    box.setWindowTitle("Synchronisation : choisir la source")
    box.setText(f"Les contenus de ce PC et de « {peer_name} » sont différents.")
    box.setInformativeText(f"{summary}\n\nÀ partir de quelle source synchroniser ?\n"
                           "• Ce PC : ses fichiers remplacent ceux de l'autre en cas de différence.\n"
                           "• L'autre PC : l'inverse.\n"
                           "• Le principal gagne : le PC principal l'emporte (les versions perdantes sont gardées "
                           "à côté).\nLes fichiers présents d'un seul côté sont de toute façon copiés des deux côtés.")
    local = box.addButton("Ce PC", QMessageBox.AcceptRole)
    remote = box.addButton("L'autre PC", QMessageBox.AcceptRole)
    primary = box.addButton("Le principal gagne", QMessageBox.AcceptRole)
    box.addButton("Annuler", QMessageBox.RejectRole)
    box.exec()
    clicked = box.clickedButton()
    return {local: "local", remote: "remote", primary: "primary"}.get(clicked, "")


class SyncDialog(QDialog):
    def __init__(self, parent=None, bridge: SyncBridge | None = None):
        super().__init__(parent)
        self.svc = get_service()
        self.s = self.svc.settings
        self.setWindowTitle("Synchronisation entre PC")
        self.setMinimumSize(640, 520)
        self._bridge = bridge or SyncBridge(self.svc)
        self._bridge.changed.connect(self._refresh)
        tabs = QTabWidget()
        tabs.addTab(self._build_devices(), "💻 Appareils")
        tabs.addTab(self._build_content(), "📦 Contenu")
        tabs.addTab(self._build_auto(), "⚙️ Automatisme")
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Save).setText("Enregistrer")
        buttons.button(QDialogButtonBox.Close).setText("Fermer")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root = QVBoxLayout(self)
        root.addWidget(tabs)
        root.addWidget(buttons)
        self._timer = QTimer(self)
        self._timer.timeout.connect(lambda: self._refresh(self.svc.snapshot()))
        self._timer.start(2000)
        self._refresh(self.svc.snapshot())

    # ── onglets ──────────────────────────────────────────────────────────────

    def _build_devices(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        form = QFormLayout()
        self.name = QLineEdit(self.s["device_name"])
        form.addRow("Nom de ce PC", self.name)
        self.primary = QComboBox()
        form.addRow("PC principal (prioritaire en cas de conflit)", self.primary)
        lay.addLayout(form)
        self.peers_box = QVBoxLayout()
        lay.addLayout(self.peers_box)
        self.empty = QLabel("Aucun autre PC appairé.\nSur le PC principal : « Créer un code ». Sur l'autre PC : "
                            "« Saisir un code ». Les deux PC doivent être sur le même réseau (LAN ou Tailscale).")
        self.empty.setWordWrap(True)
        lay.addWidget(self.empty)
        row = QHBoxLayout()
        make = QPushButton("➕ Créer un code d'appairage")
        make.clicked.connect(self._make_code)
        join = QPushButton("🔑 Saisir un code")
        join.clicked.connect(self._join)
        row.addWidget(make)
        row.addWidget(join)
        row.addStretch()
        lay.addLayout(row)
        lay.addStretch()
        self.addr = QLabel("")
        self.addr.setStyleSheet("color:#7f849c;")
        lay.addWidget(self.addr)
        return page

    def _build_content(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        self.cats: dict[str, QCheckBox] = {}
        for key, label in CATEGORIES.items():
            box = QCheckBox(label)
            box.setChecked(self.s.category(key))
            self.cats[key] = box
            lay.addWidget(box)
        self.git = QCheckBox("Inclure l'historique git (.git) — en cas de conflit, celui du principal est gardé")
        self.git.setChecked(bool(self.s["include_git"]))
        self.regen = QCheckBox("Inclure caches, node_modules, dossiers de compilation (lourd, inutile)")
        self.regen.setChecked(bool(self.s["include_regenerable"]))
        self.deletes = QCheckBox("Propager les suppressions (corbeille récupérable pendant 30 jours)")
        self.deletes.setChecked(bool(self.s["propagate_deletes"]))
        for box in (self.git, self.regen, self.deletes):
            lay.addWidget(box)
        form = QFormLayout()
        self.maxmb = QSpinBox()
        self.maxmb.setRange(1, 100000)
        self.maxmb.setSuffix(" Mo")
        self.maxmb.setValue(int(self.s["max_file_mb"]))
        form.addRow("Taille maximale d'un fichier", self.maxmb)
        self.exclude = QLineEdit(", ".join(self.s["exclude"]))
        form.addRow("Motifs ignorés", self.exclude)
        self.only = QLineEdit(", ".join(self.s["only_projects"]))
        self.only.setPlaceholderText("vide = tous les projets ; sinon noms séparés par des virgules")
        form.addRow("Projets concernés", self.only)
        lay.addLayout(form)
        note = QLabel("Jamais synchronisés : jetons, mots de passe, coffre (vault), compte GitHub, géométrie de "
                      "fenêtre et chemins propres à chaque PC.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#7f849c;")
        lay.addWidget(note)
        lay.addStretch()
        return page

    def _build_auto(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.enabled = QCheckBox("Activer la synchronisation")
        self.enabled.setChecked(bool(self.s["enabled"]))
        self.auto = QCheckBox("Synchroniser automatiquement dès que l'autre PC est sur le même réseau")
        self.auto.setChecked(bool(self.s["auto"]))
        self.interval = QSpinBox()
        self.interval.setRange(5, 3600)
        self.interval.setSuffix(" s")
        self.interval.setValue(int(self.s["interval"]))
        self.policy = QComboBox()
        self.policy.addItem("Me demander la source", "ask")
        self.policy.addItem("Le principal gagne", "primary")
        self.policy.addItem("Fusion intelligente (le principal gagne si conflit)", "smart")
        self.policy.setCurrentIndex(max(0, self.policy.findData(self.s["policy"])))
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(int(self.s["port"] or DEFAULT_PORT))
        form.addRow(self.enabled)
        form.addRow(self.auto)
        form.addRow("Recherche de l'autre PC toutes les", self.interval)
        form.addRow("Premier échange si les contenus diffèrent", self.policy)
        form.addRow("Port d'écoute (TCP)", self.port)
        info = QLabel("La synchronisation ne tourne que si l'autre PC est sur le même réseau (LAN privé ou Tailscale). "
                      "Si un PC s'éteint ou perd le réseau, elle s'arrête et reprend toute seule au retour.\n"
                      "Tout est chiffré (AES-256-GCM) et authentifié ; ouvrez le port ci-dessus dans le pare-feu "
                      "si besoin (l'interface Tailscale est en général déjà autorisée).")
        info.setWordWrap(True)
        info.setStyleSheet("color:#7f849c;")
        form.addRow(info)
        return page

    # ── actions ──────────────────────────────────────────────────────────────

    def _apply(self) -> None:
        s = self.s
        s["device_name"] = self.name.text().strip() or s["device_name"]
        pid = self.primary.currentData()
        if pid:
            s.set_primary(pid)
        for key, box in self.cats.items():
            s["categories"][key] = box.isChecked()
        s["include_git"], s["include_regenerable"] = self.git.isChecked(), self.regen.isChecked()
        s["propagate_deletes"], s["max_file_mb"] = self.deletes.isChecked(), self.maxmb.value()
        s["exclude"] = [p.strip() for p in self.exclude.text().split(",") if p.strip()]
        s["only_projects"] = [p.strip() for p in self.only.text().split(",") if p.strip()]
        s["enabled"], s["auto"] = self.enabled.isChecked(), self.auto.isChecked()
        s["interval"], s["policy"], s["port"] = self.interval.value(), self.policy.currentData(), self.port.value()
        s.save()

    def _save(self) -> None:
        self._apply()
        if self.s["enabled"]:
            self.svc.restart()
        else:
            self.svc.stop()
        self.accept()

    def _make_code(self) -> None:
        self._apply()
        if not self.s["enabled"]:
            self.s["enabled"] = True
            self.enabled.setChecked(True)
            self.s.save()
        self.svc.restart()
        code = self.svc.create_invite()
        QGuiApplication.clipboard().setText(code)
        box = QInputDialog(self)
        box.setWindowTitle("Code d'appairage")
        box.setLabelText("Saisissez ce code sur l'autre PC (valable 10 minutes, usage unique, déjà copié) :")
        box.setTextValue(code)
        box.exec()
        self._refresh(self.svc.snapshot())

    def _join(self) -> None:
        code, ok = QInputDialog.getText(self, "Saisir un code", "Code d'appairage (VKS1-…) affiché sur l'autre PC :")
        if not ok or not code.strip():
            return
        self._apply()
        try:
            reply = self.svc.join(code)
        except (ValueError, ConnectionError, Exception) as exc:  # noqa: BLE001 — message utilisateur
            QMessageBox.warning(self, "Appairage impossible", str(exc))
            return
        QMessageBox.information(self, "Appairé", f"Ce PC est maintenant lié à « {reply.get('name', '')} ».\n"
                                "Le PC qui a créé le code est le principal ; vous pouvez changer cela ici.")
        self._refresh(self.svc.snapshot())

    def _forget(self, peer_id: str) -> None:
        if QMessageBox.question(self, "Oublier ce PC", "Retirer cet appairage ? Les fichiers ne sont pas supprimés.") \
                == QMessageBox.Yes:
            self.svc.forget(peer_id)

    def _sync_now(self, peer_id: str) -> None:
        import threading
        self.s["enabled"] = True
        threading.Thread(target=self.svc.sync_peer, args=(peer_id,), daemon=True, name="voktora-sync-now").start()

    # ── rafraîchissement ─────────────────────────────────────────────────────

    def _refresh(self, snap: dict) -> None:
        s = self.s
        self.primary.blockSignals(True)
        self.primary.clear()
        self.primary.addItem(f"{s['device_name']} (ce PC)", s.device_id)
        for peer in s["peers"]:
            self.primary.addItem(peer["name"], peer["id"])
        self.primary.setCurrentIndex(max(0, self.primary.findData(s["primary_id"])))
        self.primary.blockSignals(False)
        while self.peers_box.count():
            item = self.peers_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.empty.setVisible(not s["peers"])
        for peer in s["peers"]:
            st = snap["peers"].get(peer["id"], {})
            frame = QWidget()
            row = QVBoxLayout(frame)
            row.setContentsMargins(0, 4, 0, 4)
            title = QLabel(f"<b>{peer['name']}</b>"
                           f"{' — PC principal' if s['primary_id'] == peer['id'] else ''}   "
                           f"{STATE_LABEL.get(st.get('state', 'offline'), '')}   <span style='color:#7f849c'>"
                           f"{peer['host']}:{peer['port']}</span>")
            row.addWidget(title)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(int(st.get("percent", 0)))
            row.addWidget(bar)
            remote = st.get("remote") or {}
            detail = st.get("detail", "")
            if remote.get("state") == "syncing":
                detail += f"   (l'autre PC : {remote.get('percent', 0)} %)"
            if st.get("last_sync"):
                detail += "   dernière synchro : " + time.strftime("%d/%m %H:%M", time.localtime(st["last_sync"]))
            info = QLabel(f"{detail}\n{st.get('summary', '')}".strip())
            info.setWordWrap(True)
            info.setStyleSheet("color:#7f849c;")
            row.addWidget(info)
            buttons = QHBoxLayout()
            now = QPushButton("Synchroniser maintenant")
            now.clicked.connect(lambda _=False, pid=peer["id"]: self._sync_now(pid))
            forget = QPushButton("Oublier")
            forget.clicked.connect(lambda _=False, pid=peer["id"]: self._forget(pid))
            buttons.addWidget(now)
            buttons.addWidget(forget)
            buttons.addStretch()
            row.addLayout(buttons)
            self.peers_box.addWidget(frame)
        from sync import net
        addrs = net.local_addresses()
        self.addr.setText("Adresses de ce PC — Tailscale : " + (", ".join(addrs["tailscale"]) or "aucune")
                          + "  |  LAN : " + (", ".join(addrs["lan"]) or "aucune"))

