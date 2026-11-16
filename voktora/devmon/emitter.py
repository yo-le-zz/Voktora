"""devmon.emitter — côté application : branche tous les points d'observation et écrit dans le journal de la session."""

from __future__ import annotations

import faulthandler
import logging
import os
import sys
import threading
import time
import traceback
from pathlib import Path

from . import core

_PRIVATE_TITLES = ("coffre", "vault", "mot de passe", "password", "jeton", "token", "secret", "passphrase")
_FREEZE_SECONDS = 2.0
_HEARTBEAT_SECONDS = 2.0

_current: Emitter | None = None


def current() -> Emitter | None:
    return _current


class Emitter:
    def __init__(self, level: str = "normal", session: Path | None = None, secret: bytes | None = None):
        self.level = core.valid_level(level)
        self.session = Path(session) if session else core.new_session()
        self.secret = secret if secret is not None else os.urandom(32)     # partagé avec le moniteur par un tube anonyme
        self.codec = core.Codec(self.secret)
        self.writer = core.Writer(self.session, codec=self.codec)
        self._ctl_counter = 0
        self._stop = threading.Event()
        self._tick = time.monotonic()
        self._frozen = False
        self._undo: list = []
        self._crash_fh = None
        self._filter = None
        self._started = False

    # ── émission ────────────────────────────────────────────────────────────────
    def enabled(self, need: str) -> bool:
        return core.RANK[self.level] >= core.RANK[need]

    def emit(self, cat: str, msg: str, *, sev: str = "info", need: str = "normal", src: str = "voktora", data: dict | None = None) -> None:
        if not self.enabled(need):
            return
        try:
            self.writer.write(core.make_event(cat, msg, sev, src, data))
        except Exception:  # noqa: BLE001 — l'observateur ne doit JAMAIS casser l'application
            pass

    def set_level(self, level: str) -> None:
        level = core.valid_level(level, self.level)
        if level != self.level:
            old, self.level = self.level, level
            self.writer.write(core.make_event("app", f"Mode changé : {old} → {level}", "info", "devmon", {"event": "mode", "mode": level}))
            self._apply_logging_level()

    # ── démarrage / arrêt ───────────────────────────────────────────────────────
    def start(self, app=None) -> None:
        global _current
        if self._started:
            return
        self._started = True
        _current = self
        import importlib
        version = importlib.import_module("core").APP_VERSION
        self.writer.write(core.make_event("app", f"Voktora {version} démarré — mode {self.level}", "info", "devmon", {
            "event": "start", "mode": self.level, "pid": os.getpid(), "python": sys.version.split()[0],
            "platform": sys.platform, "argv": [os.path.basename(a) for a in sys.argv[:1]]}))
        self._install_exception_hooks()
        self._install_faulthandler()
        self._install_logging()
        self._install_core_wrappers()
        if app is not None:
            self._install_qt(app)
        threading.Thread(target=self._heartbeat, name="devmon-heartbeat", daemon=True).start()
        import atexit
        atexit.register(self.stop)

    def stop(self, code: int = 0) -> None:
        if not self._started:
            return
        self._started = False
        self._stop.set()
        self.writer.write(core.make_event("app", "Voktora s'arrête", "info", "devmon", {"event": "exit", "code": code}))
        for undo in reversed(self._undo):
            try:
                undo()
            except Exception:  # noqa: BLE001
                pass
        self._undo.clear()
        try:
            faulthandler.disable()
            if self._crash_fh:
                self._crash_fh.close()
                try:
                    if core.crash_file(self.session).stat().st_size == 0:
                        core.crash_file(self.session).unlink()
                except OSError:
                    pass
        except Exception:  # noqa: BLE001
            pass
        self.writer.close()
        global _current
        _current = None

    # ── exceptions ──────────────────────────────────────────────────────────────
    def _install_exception_hooks(self) -> None:
        prev_exc, prev_thr, prev_unr = sys.excepthook, threading.excepthook, sys.unraisablehook

        def exc_hook(etype, value, tb):
            self.emit("crash", f"Exception non gérée : {etype.__name__}: {value}", sev="critical", need="crash", src="excepthook",
                      data={"traceback": "".join(traceback.format_exception(etype, value, tb))})
            prev_exc(etype, value, tb)

        def thr_hook(args):
            name = args.thread.name if args.thread else "?"
            self.emit("crash", f"Exception non gérée dans le thread {name} : {args.exc_type.__name__}: {args.exc_value}", sev="critical",
                      need="crash", src="threading", data={"traceback": "".join(traceback.format_exception(
                          args.exc_type, args.exc_value, args.exc_traceback))})
            prev_thr(args)

        def unr_hook(args):
            self.emit("crash", f"Exception ignorée : {args.exc_type.__name__ if args.exc_type else '?'}: {args.exc_value}",
                      sev="error", need="normal", src="unraisable", data={"object": repr(args.object)[:200]})
            prev_unr(args)

        sys.excepthook, threading.excepthook, sys.unraisablehook = exc_hook, thr_hook, unr_hook

        def undo():
            sys.excepthook, threading.excepthook, sys.unraisablehook = prev_exc, prev_thr, prev_unr
        self._undo.append(undo)

    def _install_faulthandler(self) -> None:
        try:
            self._crash_fh = open(core.crash_file(self.session), "w", encoding="utf-8")  # noqa: SIM115
            faulthandler.enable(self._crash_fh, all_threads=True)
        except Exception:  # noqa: BLE001
            self._crash_fh = None

    # ── journaux Python ─────────────────────────────────────────────────────────
    def _install_logging(self) -> None:
        emitter = self

        class Handler(logging.Handler):
            def emit(self, record):  # noqa: A003
                try:
                    sev = {10: "debug", 20: "info", 30: "warning", 40: "error", 50: "critical"}.get(record.levelno // 10 * 10, "info")
                    need = "trace" if sev == "debug" else ("normal" if sev in ("warning", "error", "critical") else "verbose")
                    data = None
                    if record.exc_info:
                        data = {"traceback": "".join(traceback.format_exception(*record.exc_info))}
                    emitter.emit("log", record.getMessage(), sev=sev, need=need, src=record.name, data=data)
                except Exception:  # noqa: BLE001
                    pass

        self._handler = Handler(level=logging.DEBUG)
        root = logging.getLogger()
        self._saved_level = root.level
        root.addHandler(self._handler)
        self._apply_logging_level()

        def undo():
            root.removeHandler(self._handler)
            root.setLevel(self._saved_level)
        self._undo.append(undo)

    def _apply_logging_level(self) -> None:
        if hasattr(self, "_handler"):
            logging.getLogger().setLevel(logging.DEBUG if self.enabled("trace") else min(self._saved_level or 30, 20))

    # ── cœur de Voktora : plugins, configuration ────────────────────────────────
    def _install_core_wrappers(self) -> None:
        try:
            from plugins import devtools
            devtools.subscribe(lambda e: self.emit("plugin", str(e.get("text", ""))[:1500], sev="error" if e.get("kind") == "error" else "info",
                                                   need="normal", src=str(e.get("source", "plugin"))))
        except Exception:  # noqa: BLE001
            pass
        try:
            from plugins import runtime
            original = runtime.fire_hook

            def wrapped(hook_name, *a, **kw):
                self.emit("hook", f"Hook {hook_name}", need="verbose", src="plugins")
                started = time.perf_counter()
                try:
                    return original(hook_name, *a, **kw)
                finally:
                    ms = (time.perf_counter() - started) * 1000
                    self.emit("hook", f"Hook {hook_name} terminé en {ms:.0f} ms", sev="warning" if ms > 500 else "debug",
                              need="trace", src="plugins", data={"ms": round(ms, 1)})
            runtime.fire_hook = wrapped
            self._undo.append(lambda: setattr(runtime, "fire_hook", original))
        except Exception:  # noqa: BLE001
            pass
        try:
            from core import config_store
            original_save = config_store._save_config

            def wrapped_save(cfg):
                self.emit("config", "Configuration enregistrée", need="verbose", src="config")
                return original_save(cfg)
            config_store._save_config = wrapped_save
            self._undo.append(lambda: setattr(config_store, "_save_config", original_save))
        except Exception:  # noqa: BLE001
            pass

    # ── Qt ──────────────────────────────────────────────────────────────────────
    def _install_qt(self, app) -> None:
        from PySide6.QtCore import QObject, QTimer, QtMsgType, qInstallMessageHandler

        severity = {QtMsgType.QtDebugMsg: "debug", QtMsgType.QtInfoMsg: "info", QtMsgType.QtWarningMsg: "warning",
                    QtMsgType.QtCriticalMsg: "error", QtMsgType.QtFatalMsg: "critical"}

        def handler(kind, _ctx, message):
            sev = severity.get(kind, "info")
            self.emit("qt", message, sev=sev, need="normal" if sev in ("error", "critical") else "trace", src="qt")
        previous = qInstallMessageHandler(handler)
        self._undo.append(lambda: qInstallMessageHandler(previous))

        emitter = self

        class Watcher(QObject):
            def eventFilter(self, obj, event):  # noqa: N802
                try:
                    emitter._on_event(obj, event)
                except Exception:  # noqa: BLE001
                    pass
                return False

        self._filter = Watcher(app)
        app.installEventFilter(self._filter)
        self._undo.append(lambda: app.removeEventFilter(self._filter))
        self._timer = QTimer(app)                       # bat dans le fil principal : sert au détecteur de blocage
        self._timer.timeout.connect(self._beat)
        self._timer.start(500)
        app.aboutToQuit.connect(lambda: self.emit("app", "Fermeture demandée", need="normal", src="devmon"))

    def _beat(self) -> None:
        self._tick = time.monotonic()
        if self._frozen:
            self._frozen = False
            self.emit("freeze", "L'interface répond de nouveau", need="verbose", src="watchdog")

    @staticmethod
    def _private(widget) -> bool:
        node = widget
        while node is not None:
            title = ""
            try:
                title = (node.windowTitle() or "").lower() if node.isWindow() else ""
            except Exception:  # noqa: BLE001
                pass
            if any(word in title for word in _PRIVATE_TITLES):
                return True
            node = node.parentWidget() if hasattr(node, "parentWidget") else None
        return False

    def _describe(self, widget, pos=None) -> str:
        from PySide6.QtWidgets import QAbstractButton, QMenu, QTabBar
        name = type(widget).__name__
        obj = widget.objectName()
        label = ""
        if isinstance(widget, QAbstractButton):
            label = widget.text().replace("&", "")
        elif isinstance(widget, QTabBar) and pos is not None:
            index = widget.tabAt(pos)
            label = widget.tabText(index) if index >= 0 else ""
        elif isinstance(widget, QMenu) and pos is not None:
            action = widget.actionAt(pos)
            label = action.text().replace("&", "") if action else ""
        window = widget.window()
        where = window.windowTitle() if window is not None and window is not widget else ""
        return " · ".join(p for p in (name + (f"#{obj}" if obj else ""), f"« {label} »" if label else "", f"dans « {where} »" if where else "") if p)

    def _on_event(self, obj, event) -> None:
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtWidgets import QWidget
        if not isinstance(obj, QWidget):
            return
        kind = event.type()
        if kind == QEvent.Type.Show and self.enabled("verbose") and not obj.property("_devmon") and not self._private(obj):
            self._watch_widget(obj)
        if kind == QEvent.Type.MouseButtonRelease and self.enabled("verbose"):
            if self._private(obj):
                return
            button = {Qt.MouseButton.LeftButton: "gauche", Qt.MouseButton.RightButton: "droit", Qt.MouseButton.MiddleButton: "milieu"}.get(
                event.button(), "autre")
            self.emit("click", f"Clic {button} sur {self._describe(obj, event.position().toPoint())}", need="verbose", src="ui")
        elif kind == QEvent.Type.KeyPress and self.enabled("verbose"):
            mods = event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier)
            if mods and not self._private(obj):
                from PySide6.QtGui import QKeySequence
                combo = QKeySequence(event.keyCombination()).toString()
                if combo and not combo.endswith("+"):           # jamais de caractère seul : on ne journalise pas la frappe
                    self.emit("shortcut", f"Raccourci {combo}", need="verbose", src="ui")
        elif kind == QEvent.Type.Show and obj.isWindow() and self.enabled("normal"):
            if not self._private(obj):
                self.emit("window", f"Fenêtre ouverte : {type(obj).__name__} « {obj.windowTitle()} »", need="normal", src="ui")
        elif kind == QEvent.Type.Hide and obj.isWindow() and self.enabled("verbose") and not self._private(obj):
            self.emit("window", f"Fenêtre fermée : {type(obj).__name__} « {obj.windowTitle()} »", need="verbose", src="ui")
        elif kind == QEvent.Type.KeyPress and self.enabled("verbose") and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            from PySide6.QtWidgets import QMenu
            if isinstance(obj, QMenu) and obj.activeAction() and not self._private(obj):
                self.emit("menu", f"Entrée sur « {obj.activeAction().text().replace('&', '')} »", need="verbose", src="ui")
        elif kind == QEvent.Type.WindowActivate and obj.isWindow() and self.enabled("verbose") and not self._private(obj):
            self.emit("window", f"Fenêtre active : {type(obj).__name__} « {obj.windowTitle()} »", need="verbose", src="ui")
        elif kind == QEvent.Type.FocusIn and self.enabled("trace") and not self._private(obj):
            self.emit("focus", f"Focus : {type(obj).__name__}", need="trace", src="ui")

    def _watch_widget(self, obj) -> None:
        """Branche (une seule fois) les signaux utiles d'un widget : changement d'onglet, menu ouvert/action, choix dans une liste."""
        if obj.property("_devmon"):
            return
        from PySide6.QtWidgets import QComboBox, QMenu, QTabBar, QTabWidget
        obj.setProperty("_devmon", True)
        if isinstance(obj, QTabBar):
            obj.currentChanged.connect(lambda i, w=obj: self.emit(
                "tab", f"Onglet « {w.tabText(i)} » ({type(w.parentWidget()).__name__ if w.parentWidget() else 'QTabBar'})", need="verbose", src="ui"))
        elif isinstance(obj, QTabWidget):
            obj.currentChanged.connect(lambda i, w=obj: self.emit("tab", f"Onglet « {w.tabText(i)} »", need="verbose", src="ui"))
        elif isinstance(obj, QMenu):
            self.emit("menu", f"Menu ouvert : « {obj.title().replace('&', '') or type(obj).__name__} »", need="verbose", src="ui")
            obj.triggered.connect(lambda a: self.emit("menu", f"Action : « {a.text().replace('&', '')} »", need="verbose", src="ui"))
            obj.aboutToShow.connect(lambda m=obj: self.emit("menu", f"Menu ouvert : « {m.title().replace('&', '') or 'contextuel'} »",
                                                            need="verbose", src="ui"))
        elif isinstance(obj, QComboBox):
            obj.activated.connect(lambda i, w=obj: self.emit(
                "choice", f"Choix n°{i} dans {type(w).__name__}{('#' + w.objectName()) if w.objectName() else ''}", need="verbose", src="ui"))

    # ── battement de cœur, blocages, commande ───────────────────────────────────
    def _heartbeat(self) -> None:
        control = core.control_file(self.session)
        last_mtime = 0.0
        while not self._stop.wait(_HEARTBEAT_SECONDS / 2):
            now = time.monotonic()
            if self.enabled("verbose") and not self._frozen and self._timer_alive() and now - self._tick > _FREEZE_SECONDS:
                self._frozen = True
                main = sys._current_frames().get(threading.main_thread().ident)
                stack = "".join(traceback.format_stack(main)) if main else ""
                self.emit("freeze", f"L'interface ne répond plus depuis {now - self._tick:.1f} s", sev="warning", need="verbose",
                          src="watchdog", data={"traceback": stack})
            try:
                mtime = control.stat().st_mtime
                if mtime != last_mtime:
                    last_mtime = mtime
                    cmd = core.read_control(self.session, self.codec, self._ctl_counter)   # authentifiée + anti-rejeu
                    if cmd:
                        self._ctl_counter = cmd[1]
                        self.set_level(cmd[0])
                    else:
                        self.emit("security", "Commande de contrôle rejetée (non authentifiée ou rejouée)", sev="warning", need="crash",
                                  src="devmon")
            except OSError:
                pass
            self._beat_count = getattr(self, "_beat_count", 0) + 1
            if self._beat_count % 2 == 0:
                self.writer.write({"sev": "debug", "cat": "heartbeat", "src": "devmon", "msg": "", "data": {"pid": os.getpid(), "rss_mb": _rss_mb(),
                                                                                                             "threads": threading.active_count()}})

    def _timer_alive(self) -> bool:
        return getattr(self, "_timer", None) is not None


def _rss_mb() -> int | None:
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) // 1024
    except (OSError, ValueError):
        pass
    return None


def start(level: str, app=None, secret: bytes | None = None) -> Emitter:
    em = Emitter(level, secret=secret)
    em.start(app)
    return em
