"""
Voktora — ui_dialogs.migrate_dialog
Fragment de ui_dialogs.py extrait lors du découpage v1.0.2 en package.
"""

from __future__ import annotations

import re
import socket
import sys
from datetime import datetime
from pathlib import Path

import mc
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# ════════════ migrate_dialog.py ════════════

def _safe_hostname() -> str:
    """Nom d'hôte courant, assaini pour servir de nom de fichier."""
    try:
        name = socket.gethostname() or "pc"
    except OSError:
        name = "pc"
    return re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_") or "pc"


class ExportWorker(QThread):
    progress_signal = Signal(str, int)
    finished        = Signal(bool, str, list, list)

    def __init__(self, dest: Path):
        super().__init__()
        self._dest = dest

    def run(self) -> None:
        res = mc.export_bundle(
            self._dest,
            on_progress=lambda msg, pct: self.progress_signal.emit(msg, pct),
        )
        self.finished.emit(res.success, res.message, res.log, res.warnings)



class ImportWorker(QThread):
    progress_signal = Signal(str, int)
    finished        = Signal(bool, str, list, list)

    def __init__(self, src: Path, base: Path, rules: list):
        super().__init__()
        self._src   = src
        self._base  = base
        self._rules = rules

    def run(self) -> None:
        res = mc.import_bundle(
            self._src, self._base,
            custom_rules=self._rules,
            on_progress=lambda msg, pct: self.progress_signal.emit(msg, pct),
        )
        self.finished.emit(res.success, res.message, res.log, res.warnings)


# ──────────────────────────────────────────────
# DIALOGUE PRINCIPAL
# ──────────────────────────────────────────────


class MigrateDialog(QDialog):
    """
    Dialogue de migration complète.
    Deux onglets : Export (créer bundle) et Import (restaurer bundle).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🔀 Migration de projets — Voktora")
        self.setModal(True)
        self.setMinimumSize(640, 580)

        self._export_worker: ExportWorker | None = None
        self._import_worker: ImportWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(12)

        # ── En-tête ──
        hdr = QLabel(
            "🔀 <b>Migration Voktora</b> — Transfert de projets Windows ↔ Linux"
        )
        hdr.setWordWrap(True)
        layout.addWidget(hdr)

        desc = QLabel(
            "Exportez un bundle <b>.mpack</b> depuis cette machine, puis importez-le "
            "sur la machine cible. Les chemins sont remappés automatiquement."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #a6adc8; font-size: 12px;")
        layout.addWidget(desc)

        # ── Onglets ──
        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_export_tab(), "📤 Exporter (cette machine)")
        self._tabs.addTab(self._build_import_tab(), "📥 Importer (bundle reçu)")
        layout.addWidget(self._tabs)

        # ── Journal ──
        log_group = QGroupBox("📋 Journal")
        log_layout = QVBoxLayout()
        self._log_edit = QTextEdit()
        self._log_edit.setReadOnly(True)
        self._log_edit.setMaximumHeight(160)
        self._log_edit.setObjectName("noteEdit")
        log_layout.addWidget(self._log_edit)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)

        # ── Barre de progression ──
        self._progress_lbl = QLabel("")
        self._progress_lbl.setStyleSheet("color: #a6adc8; font-size: 11px;")
        layout.addWidget(self._progress_lbl)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(False)
        layout.addWidget(self._progress_bar)

        # ── Bouton fermer ──
        btn_row = QHBoxLayout()
        self._btn_close = QPushButton("Fermer")
        self._btn_close.clicked.connect(self.accept)
        btn_row.addStretch()
        btn_row.addWidget(self._btn_close)
        layout.addLayout(btn_row)

    # ──────────────────────────────────────────────
    # ONGLET EXPORT
    # ──────────────────────────────────────────────

    def _build_export_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # Info plateforme
        import core as _core
        platform_str = "Windows" if sys.platform == "win32" else "Linux/RPi"
        info = QLabel(
            f"Plateforme actuelle : <b>{platform_str}</b>\n"
            f"Version Voktora    : <b>v{_core.APP_VERSION}</b>"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        grp = QGroupBox("📦 Destination du bundle")
        form = QFormLayout()

        self._export_dest_edit = QLineEdit()
        self._export_dest_edit.setPlaceholderText("Chemin du fichier .mpack à créer…")
        btn_browse = QPushButton("…")
        btn_browse.setFixedWidth(32)
        btn_browse.clicked.connect(self._browse_export_dest)
        row = QHBoxLayout()
        row.addWidget(self._export_dest_edit)
        row.addWidget(btn_browse)
        form.addRow("Fichier .mpack :", row)

        # Préfiller un nom par défaut
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        host = _safe_hostname()
        default_name = f"voktora_{host}_{ts}.mpack"
        default_path = Path.home() / default_name
        self._export_dest_edit.setText(str(default_path))

        grp.setLayout(form)
        layout.addWidget(grp)

        # Résumé des projets à exporter
        grp2 = QGroupBox("📋 Projets inclus dans le bundle")
        grp2_layout = QVBoxLayout()
        self._export_summary = QLabel(self._build_export_summary())
        self._export_summary.setWordWrap(True)
        self._export_summary.setStyleSheet("font-size: 12px; color: #a6adc8;")
        grp2_layout.addWidget(self._export_summary)
        grp2.setLayout(grp2_layout)
        layout.addWidget(grp2)

        layout.addStretch()

        self._btn_export = QPushButton("📤 Créer le bundle de migration")
        self._btn_export.setObjectName("primary")
        self._btn_export.clicked.connect(self._start_export)
        layout.addWidget(self._btn_export)

        return w

    def _build_export_summary(self) -> str:
        try:
            import core as _core
            cfg  = _core._load_config()
            inst = cfg.get("instances", [])
            intn = cfg.get("intents",   [])
            ok_i = sum(1 for e in inst if Path(e["path"]).exists())
            ok_n = sum(1 for e in intn if Path(e["path"]).exists())
            miss_i = len(inst) - ok_i
            miss_n = len(intn) - ok_n
            lines = [
                f"  📦 Instances : {ok_i} valide(s)" +
                (f", {miss_i} absente(s) du disque" if miss_i else ""),
                f"  🌱 Intents   : {ok_n} valide(s)" +
                (f", {miss_n} absent(s) du disque" if miss_n else ""),
            ]
            return "\n".join(lines)
        except Exception as e:
            return f"Impossible de lire la config : {e}"

    def _browse_export_dest(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Choisir la destination du bundle",
            self._export_dest_edit.text() or str(Path.home()),
            "Bundle Voktora (*.mpack);;Tous les fichiers (*)"
        )
        if path:
            if not path.endswith(".mpack"):
                path += ".mpack"
            self._export_dest_edit.setText(path)

    def _start_export(self) -> None:
        dest_str = self._export_dest_edit.text().strip()
        if not dest_str:
            QMessageBox.warning(self, "Attention",
                                "Choisissez un emplacement de destination.")
            return
        dest = Path(dest_str)
        if dest.exists():
            r = QMessageBox.question(
                self, "Fichier existant",
                f"Le fichier {dest.name} existe déjà.\nL'écraser ?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if r != QMessageBox.Yes:
                return

        self._lock(True)
        self._log("─── Démarrage de l'export ───")
        self._export_worker = ExportWorker(dest)
        self._export_worker.progress_signal.connect(self._on_progress)
        self._export_worker.finished.connect(self._on_export_done)
        self._export_worker.start()

    def _on_export_done(self, ok: bool, msg: str, log: list, warn: list) -> None:
        self._lock(False)
        self._progress_bar.setVisible(False)
        self._progress_lbl.setText("")
        for line in log:
            self._log(line)
        for w in warn:
            self._log(f"⚠ {w}", color="#fab387")
        if ok:
            dest = self._export_dest_edit.text()
            self._log(f"✅ {msg}", color="#a6e3a1")
            QMessageBox.information(
                self, "Export réussi",
                f"Le bundle de migration a été créé :\n\n{dest}\n\n"
                "Copiez ce fichier sur la machine cible et utilisez l'onglet "
                "« Importer » pour restaurer vos projets."
            )
        else:
            self._log(f"❌ {msg}", color="#f38ba8")
            QMessageBox.critical(self, "Erreur d'export", msg)

    # ──────────────────────────────────────────────
    # ONGLET IMPORT
    # ──────────────────────────────────────────────

    def _build_import_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # Source
        grp_src = QGroupBox("📦 Bundle à importer")
        form_src = QFormLayout()

        self._import_src_edit = QLineEdit()
        self._import_src_edit.setPlaceholderText("Chemin du fichier .mpack…")
        self._import_src_edit.textChanged.connect(self._on_bundle_changed)
        btn_browse_src = QPushButton("…")
        btn_browse_src.setFixedWidth(32)
        btn_browse_src.clicked.connect(self._browse_import_src)
        row_src = QHBoxLayout()
        row_src.addWidget(self._import_src_edit)
        row_src.addWidget(btn_browse_src)
        form_src.addRow("Fichier .mpack :", row_src)

        # Infos bundle (remplies dynamiquement)
        self._bundle_info_lbl = QLabel("Sélectionnez un fichier .mpack pour voir ses infos.")
        self._bundle_info_lbl.setWordWrap(True)
        self._bundle_info_lbl.setStyleSheet("font-size: 11px; color: #6c7086;")
        form_src.addRow("", self._bundle_info_lbl)

        grp_src.setLayout(form_src)
        layout.addWidget(grp_src)

        # Destination
        grp_dst = QGroupBox("📁 Dossier de destination")
        form_dst = QFormLayout()

        self._import_base_edit = QLineEdit()
        default_base = str(Path.home()) if sys.platform != "win32" else "D:\\"
        self._import_base_edit.setText(default_base)
        self._import_base_edit.setPlaceholderText(
            "Dossier racine (ex: /home/ubuntu ou D:\\)"
        )
        btn_browse_dst = QPushButton("…")
        btn_browse_dst.setFixedWidth(32)
        btn_browse_dst.clicked.connect(self._browse_import_base)
        row_dst = QHBoxLayout()
        row_dst.addWidget(self._import_base_edit)
        row_dst.addWidget(btn_browse_dst)
        form_dst.addRow("Racine :", row_dst)

        hint = QLabel(
            "Les projets seront extraits dans :\n"
            "  <racine>/instances/<nom_projet>/\n"
            "  <racine>/intents/<nom_projet>/"
        )
        hint.setStyleSheet("font-size: 11px; color: #6c7086;")
        hint.setWordWrap(True)
        form_dst.addRow("", hint)

        grp_dst.setLayout(form_dst)
        layout.addWidget(grp_dst)

        # Règles de remappage personnalisées (optionnel)
        grp_rules = QGroupBox("⚙️ Remappage personnalisé (optionnel)")
        rules_layout = QVBoxLayout()

        rules_hint = QLabel(
            "Si les chemins ne sont pas remappés correctement, ajoutez des règles "
            "manuelles (format  ancien_préfixe : nouveau_préfixe)."
        )
        rules_hint.setWordWrap(True)
        rules_hint.setStyleSheet("font-size: 11px; color: #6c7086;")
        rules_layout.addWidget(rules_hint)

        self._rules_list = QListWidget()
        self._rules_list.setMaximumHeight(80)
        rules_layout.addWidget(self._rules_list)

        rule_input_row = QHBoxLayout()
        self._rule_old_edit = QLineEdit()
        self._rule_old_edit.setPlaceholderText("Ancien préfixe  ex: D:\\Projects")
        self._rule_new_edit = QLineEdit()
        self._rule_new_edit.setPlaceholderText("Nouveau préfixe  ex: /home/user/Projects")
        btn_add_rule = QPushButton("➕")
        btn_add_rule.setFixedWidth(32)
        btn_add_rule.clicked.connect(self._add_rule)
        btn_del_rule = QPushButton("🗑")
        btn_del_rule.setFixedWidth(32)
        btn_del_rule.clicked.connect(self._remove_rule)
        rule_input_row.addWidget(self._rule_old_edit)
        rule_input_row.addWidget(QLabel("→"))
        rule_input_row.addWidget(self._rule_new_edit)
        rule_input_row.addWidget(btn_add_rule)
        rule_input_row.addWidget(btn_del_rule)
        rules_layout.addLayout(rule_input_row)

        grp_rules.setLayout(rules_layout)
        layout.addWidget(grp_rules)

        layout.addStretch()

        self._btn_import = QPushButton("📥 Importer le bundle")
        self._btn_import.setObjectName("primary")
        self._btn_import.clicked.connect(self._start_import)
        layout.addWidget(self._btn_import)

        return w

    def _browse_import_src(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Sélectionner un bundle Voktora",
            str(Path.home()),
            "Bundle Voktora (*.mpack);;Fichiers ZIP (*.zip);;Tous les fichiers (*)"
        )
        if path:
            self._import_src_edit.setText(path)

    def _browse_import_base(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Choisir le dossier de destination",
            self._import_base_edit.text() or str(Path.home())
        )
        if path:
            self._import_base_edit.setText(path)

    def _on_bundle_changed(self, text: str) -> None:
        """Met à jour les infos du bundle quand l'utilisateur change le chemin."""
        p = Path(text.strip())
        if not p.exists() or not text.strip():
            self._bundle_info_lbl.setText("Sélectionnez un fichier .mpack pour voir ses infos.")
            self._bundle_info_lbl.setStyleSheet("font-size: 11px; color: #6c7086;")
            return
        info = mc.validate_bundle(p)
        if info["valid"]:
            m = info["manifest"]
            src_plat   = m.get("source_platform", "?")
            tgt_plat   = "Linux" if sys.platform != "win32" else "Windows"
            arrow      = f"{src_plat.capitalize()} → {tgt_plat}"
            n_proj     = m.get("_detected_project_count", "?")
            size_kb    = m.get("_bundle_size_kb", "?")
            created    = m.get("created_at", "?")[:16].replace("T", " ")
            self._bundle_info_lbl.setText(
                f"✅ Bundle valide  |  {arrow}  |  {n_proj} projet(s)  "
                f"|  {size_kb} Ko  |  Créé le {created}"
            )
            self._bundle_info_lbl.setStyleSheet("font-size: 11px; color: #a6e3a1;")
        else:
            self._bundle_info_lbl.setText(f"❌ {info['error']}")
            self._bundle_info_lbl.setStyleSheet("font-size: 11px; color: #f38ba8;")

    def _add_rule(self) -> None:
        old = self._rule_old_edit.text().strip()
        new = self._rule_new_edit.text().strip()
        if not old or not new:
            QMessageBox.warning(self, "Attention",
                                "Renseignez l'ancien et le nouveau préfixe.")
            return
        item = QListWidgetItem(f"{old}  →  {new}")
        item.setData(Qt.UserRole, (old, new))
        self._rules_list.addItem(item)
        self._rule_old_edit.clear()
        self._rule_new_edit.clear()

    def _remove_rule(self) -> None:
        item = self._rules_list.currentItem()
        if item:
            self._rules_list.takeItem(self._rules_list.row(item))

    def _get_rules(self) -> list:
        rules = []
        for i in range(self._rules_list.count()):
            item = self._rules_list.item(i)
            rules.append(item.data(Qt.UserRole))
        return rules

    def _start_import(self) -> None:
        src_str  = self._import_src_edit.text().strip()
        base_str = self._import_base_edit.text().strip()

        if not src_str:
            QMessageBox.warning(self, "Attention",
                                "Sélectionnez un bundle .mpack à importer.")
            return
        if not base_str:
            QMessageBox.warning(self, "Attention",
                                "Choisissez un dossier de destination.")
            return

        src  = Path(src_str)
        base = Path(base_str)

        if not src.exists():
            QMessageBox.critical(self, "Erreur",
                                 f"Bundle introuvable : {src}")
            return

        # Valider avant
        info = mc.validate_bundle(src)
        if not info["valid"]:
            QMessageBox.critical(self, "Bundle invalide", info["error"])
            return

        # Confirmation
        m = info["manifest"]
        n = m.get("_detected_project_count", "?")
        reply = QMessageBox.question(
            self, "Confirmer l'import",
            f"Importer {n} projet(s) depuis ce bundle ?\n\n"
            f"Source      : {m.get('source_platform','?')}\n"
            f"Destination : {base}\n\n"
            "⚠ La configuration locale sera remplacée.\n"
            "Créez un export de cette machine d'abord si nécessaire !",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self._lock(True)
        self._log("─── Démarrage de l'import ───")
        self._import_worker = ImportWorker(src, base, self._get_rules())
        self._import_worker.progress_signal.connect(self._on_progress)
        self._import_worker.finished.connect(self._on_import_done)
        self._import_worker.start()

    def _on_import_done(self, ok: bool, msg: str, log: list, warn: list) -> None:
        self._lock(False)
        self._progress_bar.setVisible(False)
        self._progress_lbl.setText("")
        for line in log:
            self._log(line)
        for w in warn:
            self._log(f"⚠ {w}", color="#fab387")
        if ok:
            self._log(f"✅ {msg}", color="#a6e3a1")
            QMessageBox.information(
                self, "Import réussi",
                f"{msg}\n\n"
                "🔄 Redémarrez Voktora pour charger vos projets importés."
            )
        else:
            self._log(f"❌ {msg}", color="#f38ba8")
            QMessageBox.critical(self, "Erreur d'import", msg)

    # ──────────────────────────────────────────────
    # HELPERS
    # ──────────────────────────────────────────────

    def _on_progress(self, msg: str, pct: int) -> None:
        self._progress_lbl.setText(msg)
        self._progress_bar.setValue(pct)
        self._progress_bar.setVisible(True)

    def _log(self, text: str, color: str = "") -> None:
        if color:
            self._log_edit.append(
                f'<span style="color:{color}">{text}</span>'
            )
        else:
            self._log_edit.append(text)
        self._log_edit.verticalScrollBar().setValue(
            self._log_edit.verticalScrollBar().maximum()
        )

    def _lock(self, locked: bool) -> None:
        self._btn_export.setEnabled(not locked)
        self._btn_import.setEnabled(not locked)
        self._btn_close.setEnabled(not locked)
        self._tabs.setEnabled(not locked or True)   # onglets toujours visibles
        self._progress_bar.setVisible(locked)



