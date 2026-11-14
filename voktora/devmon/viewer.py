"""devmon.viewer — la seconde fenêtre (processus séparé) : suit le journal d'une session en direct."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from . import core

SEV_COLORS = {"debug": "#8a8f98", "info": "#1f2328", "warning": "#9a6700", "error": "#cf222e", "critical": "#ffffff"}
COLUMNS = ("Heure", "Gravité", "Catégorie", "Source", "Message")


def event_matches(ev: dict, min_sev: str = "debug", cats: set[str] | None = None, text: str = "") -> bool:
    if ev.get("cat") == "heartbeat":
        return False
    if core.SEVERITIES.index(ev.get("sev", "info")) < core.SEVERITIES.index(min_sev):
        return False
    if cats and ev.get("cat") not in cats:
        return False
    if text:
        haystack = f"{ev.get('cat', '')} {ev.get('src', '')} {ev.get('msg', '')} {(ev.get('data') or {}).get('traceback', '')}".lower()
        return text.lower() in haystack
    return True


def format_event(ev: dict) -> str:
    stamp = time.strftime("%H:%M:%S", time.localtime(ev.get("t", 0))) + f".{int(ev.get('t', 0) % 1 * 1000):03d}"
    line = f"{stamp} [{ev.get('sev', 'info'):<8}] {ev.get('cat', ''):<9} {ev.get('src', '')}: {ev.get('msg', '')}"
    tb = (ev.get("data") or {}).get("traceback")
    return line + ("\n" + tb.rstrip() if tb else "")


def export_text(events: list[dict]) -> str:
    return "\n".join(format_event(e) for e in events if e.get("cat") != "heartbeat") + "\n"


def run(session_path: str) -> int:
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QBrush, QColor, QFont
    from PySide6.QtWidgets import (
        QAbstractItemView,
        QApplication,
        QCheckBox,
        QComboBox,
        QFileDialog,
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QLineEdit,
        QMainWindow,
        QPlainTextEdit,
        QPushButton,
        QSplitter,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    )

    session = Path(session_path)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("Voktora Dev Monitor")
    app.setStyle("Fusion")
    tail = core.Tail(session)
    events: list[dict] = []
    shown: list[dict] = []
    state = {"pid": 0, "follow": True, "paused": False}

    win = QMainWindow()
    win.setWindowTitle(f"Voktora — Moniteur développeur · {session.name}")
    win.resize(1100, 680)
    central = QWidget()
    win.setCentralWidget(central)
    root = QVBoxLayout(central)

    status = QLabel("En attente de Voktora…")
    status.setStyleSheet("font-weight:600;padding:4px")
    root.addWidget(status)

    bar = QHBoxLayout()
    mode_box = QComboBox()
    for key in core.LEVELS:
        mode_box.addItem(core.LABELS[key], key)
    sev_box = QComboBox()
    for s in core.SEVERITIES:
        sev_box.addItem({"debug": "Tout (debug+)", "info": "Info+", "warning": "Avertissements+", "error": "Erreurs+", "critical": "Critiques"}[s], s)
    search = QLineEdit()
    search.setPlaceholderText("Rechercher…")
    search.setClearButtonEnabled(True)
    cat_box = QComboBox()
    cat_box.addItem("Toutes les catégories", "")
    follow = QCheckBox("Suivre")
    follow.setChecked(True)
    pause = QPushButton("Pause")
    pause.setCheckable(True)
    export_btn = QPushButton("Exporter…")
    folder_btn = QPushButton("Dossier")
    clear_btn = QPushButton("Vider l'affichage")
    for w in (QLabel("Mode :"), mode_box, sev_box, cat_box, search, follow, pause, clear_btn, export_btn, folder_btn):
        bar.addWidget(w)
    bar.setStretch(4, 1)
    root.addLayout(bar)

    table = QTableWidget(0, len(COLUMNS))
    table.setHorizontalHeaderLabels(COLUMNS)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.verticalHeader().hide()
    table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
    table.setColumnWidth(0, 95)
    table.setColumnWidth(1, 80)
    table.setColumnWidth(2, 90)
    table.setColumnWidth(3, 150)
    details = QPlainTextEdit()
    details.setReadOnly(True)
    details.setFont(QFont("monospace"))
    details.setPlaceholderText("Sélectionnez une ligne pour voir le détail (traceback, données).")
    split = QSplitter(Qt.Orientation.Vertical)
    split.addWidget(table)
    split.addWidget(details)
    split.setStretchFactor(0, 4)
    split.setStretchFactor(1, 1)
    root.addWidget(split, 1)
    counter = QLabel("")
    root.addWidget(counter)

    def current_filter(ev: dict) -> bool:
        cat = cat_box.currentData()
        return event_matches(ev, sev_box.currentData(), {cat} if cat else None, search.text().strip())

    def add_row(ev: dict) -> None:
        row = table.rowCount()
        table.insertRow(row)
        stamp = time.strftime("%H:%M:%S", time.localtime(ev.get("t", 0)))
        for col, text in enumerate((stamp, ev.get("sev", ""), ev.get("cat", ""), ev.get("src", ""), ev.get("msg", ""))):
            item = QTableWidgetItem(text)
            sev = ev.get("sev", "info")
            if sev == "critical":
                item.setBackground(QBrush(QColor("#cf222e")))
                item.setForeground(QBrush(QColor("#ffffff")))
            elif sev == "error":
                item.setForeground(QBrush(QColor("#cf222e")))
            elif sev == "warning":
                item.setForeground(QBrush(QColor("#9a6700")))
            elif sev == "debug":
                item.setForeground(QBrush(QColor("#8a8f98")))
            table.setItem(row, col, item)
        shown.append(ev)

    def rebuild() -> None:
        table.setRowCount(0)
        shown.clear()
        for ev in events:
            if current_filter(ev):
                add_row(ev)
        counter.setText(f"{len(shown)} affichés sur {len([e for e in events if e.get('cat') != 'heartbeat'])} événements")

    def show_detail() -> None:
        rows = table.selectionModel().selectedRows()
        if not rows or rows[0].row() >= len(shown):
            return
        ev = shown[rows[0].row()]
        data = dict(ev.get("data") or {})
        tb = data.pop("traceback", "")
        text = format_event({**ev, "data": {}})
        if data:
            text += "\n\n" + json.dumps(data, indent=2, ensure_ascii=False)
        if tb:
            text += "\n\n" + tb
        details.setPlainText(text)

    def poll() -> None:
        new = tail.read()
        if state["paused"]:
            new_events = new
            events.extend(new_events)
        else:
            events.extend(new)
            for ev in new:
                if ev.get("cat") == "app" and (ev.get("data") or {}).get("event") == "mode":
                    mode_box.blockSignals(True)
                    mode_box.setCurrentIndex(max(0, core.RANK.get(ev["data"].get("mode"), 1)))
                    mode_box.blockSignals(False)
                if ev.get("cat") == "app" and (ev.get("data") or {}).get("event") == "start":
                    mode_box.blockSignals(True)
                    mode_box.setCurrentIndex(core.RANK.get(ev["data"].get("mode"), 1))
                    mode_box.blockSignals(False)
                cat = ev.get("cat")
                if cat and cat != "heartbeat" and cat_box.findData(cat) < 0:
                    cat_box.addItem(cat, cat)
                if ev.get("cat") == "heartbeat":
                    state["pid"] = (ev.get("data") or {}).get("pid", state["pid"])
                elif current_filter(ev):
                    add_row(ev)
            if new and follow.isChecked():
                table.scrollToBottom()
        for ev in events[-200:]:
            if ev.get("cat") == "app" and (ev.get("data") or {}).get("event") == "start":
                state["pid"] = ev["data"].get("pid", state["pid"])
        code, text = core.app_state(events[-400:] if len(events) > 400 else events, time.time(), core.pid_alive(state["pid"]))
        status.setText(text)
        color = {"running": "#1a7f37", "exited": "#57606a", "crashed": "#cf222e", "hung": "#9a6700", "waiting": "#57606a"}[code]
        status.setStyleSheet(f"font-weight:600;padding:4px;color:{color}")
        counter.setText(f"{len(shown)} affichés sur {len([e for e in events if e.get('cat') != 'heartbeat'])} événements")
        crash = core.crash_file(session)
        if code == "crashed" and crash.exists() and crash.stat().st_size and not state.get("crash_shown"):
            state["crash_shown"] = True
            details.setPlainText("Plantage natif — trace écrite par faulthandler :\n\n" + crash.read_text(encoding="utf-8", errors="replace"))

    def on_mode(_i: int) -> None:
        try:
            core.control_file(session).write_text(json.dumps({"mode": mode_box.currentData()}), encoding="utf-8")
        except OSError:
            pass

    def on_pause(on: bool) -> None:
        state["paused"] = on
        pause.setText("Reprendre" if on else "Pause")
        if not on:
            rebuild()

    def do_export() -> None:
        name, _ = QFileDialog.getSaveFileName(win, "Exporter le journal", str(session.with_suffix(".log")), "Journal (*.log *.txt)")
        if name:
            Path(name).write_text(export_text([e for e in events if current_filter(e)]), encoding="utf-8")

    def open_folder() -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(session.parent)))

    def clear_view() -> None:
        events.clear()
        rebuild()

    mode_box.currentIndexChanged.connect(on_mode)
    pause.toggled.connect(on_pause)
    for w in (sev_box, cat_box):
        w.currentIndexChanged.connect(lambda _i: rebuild())
    search.textChanged.connect(lambda _t: rebuild())
    table.itemSelectionChanged.connect(show_detail)
    export_btn.clicked.connect(do_export)
    folder_btn.clicked.connect(open_folder)
    clear_btn.clicked.connect(clear_view)

    timer = QTimer(win)
    timer.timeout.connect(poll)
    timer.start(500)
    poll()
    win.show()
    return app.exec()
