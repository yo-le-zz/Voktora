"""
Voktora — plugins.js_worker (1.1.1)
Processus de travail d'UN plugin JavaScript. Lancé par `js_host` (jamais à la main) : `main.py` l'exécute quand la
variable d'environnement VOKTORA_JS_WORKER=1 est définie (pareil dans la version compilée).

Autonome : il n'importe RIEN de Voktora (seulement la bibliothèque standard et QtQml). Le moteur JavaScript tourne dans
ce processus séparé — une boucle infinie ou un plantage ne touche pas l'application, qui peut le tuer —
et le script n'a accès qu'à l'API de plugins, relayée par l'application (qui applique les permissions).

Protocole : une ligne JSON par message, sur stdin/stdout.
  application → worker : {"t":"load","root","entry"} · {"t":"invoke","id","payload"} · {"t":"unload"} · {"t":"reply","value"}
  worker → application : {"t":"call","name","args"} · {"t":"ret","ok","value","error"}
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

MAX_MODULE_BYTES = 4 * 1024 * 1024
_PRELUDE = r"""
(function (global) {
  var fns = {}, counter = 0, cache = {};
  function enc(a) {
    if (typeof a === 'function') { var id = ++counter; fns[id] = a; return {"__fn": id}; }
    if (Array.isArray(a)) return a.map(enc);
    if (a && typeof a === 'object') { var o = {}; for (var k in a) o[k] = enc(a[k]); return o; }
    return a;
  }
  function call(name, args) {
    var out = __bridge.call(name, JSON.stringify(args.map(enc)));
    if (out === '') return undefined;
    var r = JSON.parse(out);
    if (r && typeof r === 'object' && r.__error !== undefined) throw new Error(r.__error);
    return r;
  }
  function group(prefix) {
    return new Proxy({}, { get: function (target, name) {
      if (name in target) return target[name];
      return function () { return call(prefix + String(name), Array.prototype.slice.call(arguments)); };
    }});
  }
  global.voktora = group('');
  global.voktora.options = group('options.');
  global.voktora.settings = group('settings.');
  global.console = { log: function () { call('log', [Array.prototype.join.call(arguments, ' ')]); },
                     warn: function () { call('warn', [Array.prototype.join.call(arguments, ' ')]); },
                     error: function () { call('error', [Array.prototype.join.call(arguments, ' ')]); },
                     debug: function () { call('debug', [Array.prototype.join.call(arguments, ' ')]); } };
  global.__invoke = function (id, json) {
    var r = fns[id].apply(null, JSON.parse(json));
    return r === undefined ? '' : JSON.stringify(r);
  };
  global.__setUnload = function (f) { global.__onUnload = f; };
  global.require = function (path) { return load(path, '.'); };
  function load(path, from) {
    var src = __bridge.module(path, from);
    var info = JSON.parse(src);
    if (cache[info.path]) return cache[info.path].exports;
    var module = { exports: {} };
    cache[info.path] = module;
    if (info.json) { module.exports = JSON.parse(info.source); return module.exports; }
    var tail = (from === '.') ? '\n;if (typeof onUnload === "function") __setUnload(onUnload);' : '';
    var fn = new Function('require', 'module', 'exports', info.source + tail + '\n//# sourceURL=' + info.path);
    fn(function (p) { return load(p, info.path); }, module, module.exports);
    return module.exports;
  }
  global.__run_entry = function (path) { load(path, '.'); };
})(this);
"""




_out = None
_root: Path = Path(".")


def _send(message: dict) -> None:
    _out.write(json.dumps(message) + "\n")
    _out.flush()


def _recv() -> dict:
    line = sys.stdin.readline()
    if not line:                                    # l'application a disparu : on s'arrête
        os._exit(0)
    return json.loads(line)


def run() -> None:
    global _out, _root
    _out = os.fdopen(os.dup(1), "w", buffering=1, encoding="utf-8")
    sys.stdout = sys.stderr                         # un print() ne doit pas casser le protocole
    from PySide6.QtCore import QCoreApplication, QObject, Slot
    from PySide6.QtQml import QJSEngine, QJSValue

    _app = QCoreApplication([])
    engine = QJSEngine()

    def run_js(fn):
        result = fn()
        if isinstance(result, QJSValue) and result.isError():
            file = result.property("fileName").toString()
            line = result.property("lineNumber").toInt()
            raise RuntimeError(f"{result.toString()}" + (f" ({file}:{line})" if file else ""))
        return result

    def handle(message: dict) -> None:
        global _root
        kind = message["t"]
        try:
            if kind == "load":
                _root = Path(message["root"]).resolve()
                run_js(lambda: engine.evaluate(_PRELUDE, "voktora-prelude.js"))
                run_js(lambda: engine.globalObject().property("__run_entry").call([f"./{message['entry']}"]))
                value = ""
            elif kind == "invoke":
                result = run_js(lambda: engine.globalObject().property("__invoke").call([message["id"], message["payload"]]))
                value = result.toString() if result is not None else ""
            elif kind == "unload":
                fn = engine.globalObject().property("__onUnload")
                if fn.isCallable():
                    run_js(lambda: fn.call([]))
                value = ""
            else:
                return
            _send({"t": "ret", "ok": True, "value": value})
        except Exception as exc:  # noqa: BLE001
            _send({"t": "ret", "ok": False, "error": str(exc)})

    def wait_reply() -> str:
        while True:
            message = _recv()
            if message["t"] == "reply":
                return message["value"]
            handle(message)                         # rappel déclenché pendant l'appel (ex. option modifiée)

    def read_module(path: str, origin: str) -> str:
        try:
            base = _root if origin in (".", "") else (_root / origin).parent
            target = (base / path).resolve() if path.startswith(".") else (_root / path).resolve()
            if not target.is_relative_to(_root) or target.suffix not in (".js", ".mjs", ".json"):
                raise PermissionError(f"Module refusé : {path}")
            if target.stat().st_size > MAX_MODULE_BYTES:
                raise PermissionError("Module trop volumineux.")
            return json.dumps({"path": target.relative_to(_root).as_posix(), "json": target.suffix == ".json",
                               "source": target.read_text(encoding="utf-8")})
        except (OSError, PermissionError) as exc:
            return json.dumps({"path": path, "json": False, "source": f"throw new Error({json.dumps(str(exc))});"})

    class Bridge(QObject):
        @Slot(str, str, result=str)
        def call(self, name: str, args: str) -> str:
            _send({"t": "call", "name": name, "args": args})
            return wait_reply()

        @Slot(str, str, result=str)
        def module(self, path: str, origin: str) -> str:
            return read_module(path, origin)

    bridge = Bridge()
    engine.globalObject().setProperty("__bridge", engine.newQObject(bridge))
    while True:
        message = _recv()
        handle(message)
        if message["t"] == "unload":
            os._exit(0)


if __name__ == "__main__":
    run()
