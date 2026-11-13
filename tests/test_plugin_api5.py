"""API 5 : réseau sans limite, fichiers privés, minuteries, système, fichiers de projet, outils IA, palette."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import core
import pytest
from plugins import runtime


class Host:
    window = None

    def __init__(self):
        self.answers = {}

    def post(self, fn):
        fn()

    def confirm(self, title, text):
        return self.answers.get("confirm", True)

    def log(self, m):
        pass

    def current_project(self):
        return None


def api_with(perms, tmp_path, host=True):
    info = runtime.PluginInfo(name="t", version="1", author="a", path=tmp_path, id="t", permissions=list(perms))
    runtime.set_ui_host(Host() if host else None)
    return runtime.PluginAPI(info), info


@pytest.fixture(autouse=True)
def _reset_host():
    yield
    runtime.set_ui_host(None)


class _H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.send_response(201)
        self.end_headers()
        self.wfile.write(b"echo:" + body)

    def do_GET(self):  # noqa: N802
        if self.path == "/big":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"x" * (3 * 1024 * 1024))
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"nope")


@pytest.fixture
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_http_has_no_size_limit_and_returns_error_codes(isolated_data_dir, tmp_path, server):
    api, _ = api_with(["network"], tmp_path)
    assert len(api.http_get(server + "/big")) == 3 * 1024 * 1024            # > 2 Mo : plus de limite
    with pytest.raises(runtime.PluginError, match="trop grande"):
        api.http_get(server + "/big", max_bytes=1000)
    code, body, _h = api.http_request("POST", server + "/x", body={"a": 1})
    assert code == 201 and json.loads(body[5:]) == {"a": 1}
    assert api.http_request("GET", server + "/zzz")[0] == 404


def test_http_requires_permission_and_blocks_public_http(isolated_data_dir, tmp_path):
    api, _ = api_with([], tmp_path)
    with pytest.raises(runtime.PluginError, match="permission"):
        api.http_get("https://example.org")
    api, _ = api_with(["network"], tmp_path)
    with pytest.raises(runtime.PluginError, match="https"):
        api.http_get("http://example.org/")


def test_private_files_are_sandboxed(isolated_data_dir, tmp_path):
    api, _ = api_with([], tmp_path)
    api.write_text("a/b.txt", "salut")
    assert api.read_text("a/b.txt") == "salut" and api.list_data("a") == ["b.txt"]
    assert api.read_text("nope.txt", "défaut") == "défaut"
    for bad in ("../x", "/etc/passwd", "a/../../x"):
        with pytest.raises(runtime.PluginError):
            api.data_path(bad)
    assert api.delete_data("a/b.txt") and not api.delete_data("a/b.txt")


def test_every_and_unload_stops_timer(isolated_data_dir, tmp_path):
    api, info = api_with(["ui"], tmp_path)
    hits = []
    api.every(0.2, lambda: hits.append(1))
    time.sleep(0.7)
    assert len(hits) >= 2
    runtime.unload(info)
    n = len(hits)
    time.sleep(0.5)
    assert len(hits) <= n + 1


def test_system_info(isolated_data_dir, tmp_path):
    api, _ = api_with(["system"], tmp_path)
    snap = api.system_info()
    assert snap["memory"]["total"] > 0 and snap["cpu_count"] >= 1 and snap["disks"]
    api2, _ = api_with([], tmp_path)
    with pytest.raises(runtime.PluginError):
        api2.system_info()


def test_project_files_read_write(isolated_data_dir, tmp_path):
    proj = tmp_path / "p"
    proj.mkdir()
    (proj / "a.py").write_text("print(1)")
    core.register_project(proj, name="p", category="Perso")
    api, _ = api_with(["files", "files.write"], tmp_path)
    assert api.project_files(proj, "*.py") == ["a.py"] and api.project_read_text(proj, "a.py") == "print(1)"
    with pytest.raises(runtime.PluginError):
        api.project_read_text(proj, "../x")
    with pytest.raises(runtime.PluginError):
        api.project_files(tmp_path, "*")                                   # pas un projet enregistré
    api.project_write_text(proj, "n/b.txt", "ok")
    assert (proj / "n" / "b.txt").read_text() == "ok"
    runtime._ui_host.answers["confirm"] = False
    with pytest.raises(runtime.PluginError):
        api.project_write_text(proj, "c.txt", "non")


def test_ai_tool_and_palette_registry(isolated_data_dir, tmp_path):
    api, info = api_with(["ai.tools", "ui"], tmp_path)
    info.loaded = True
    api.register_ai_tool("hello", "Dit bonjour", lambda a: "salut " + a.get("who", ""), {"who": "nom"})
    api.add_palette_command("Faire un truc", lambda: None)
    import ai_agent
    tools = ai_agent.build_tools()
    assert "t_hello" in tools and tools["t_hello"].permission == "plugins.tools"
    assert tools["t_hello"].handler({"who": "toi"}) == "salut toi"
    assert runtime.palette_entries()[0][0] == "t › Faire un truc"
    runtime.unload(info)
    assert "t_hello" not in ai_agent.build_tools() and not runtime.palette_entries()
    with pytest.raises(runtime.PluginError):
        api_with([], tmp_path)[0].register_ai_tool("x_y", "d", lambda a: "")


def test_permission_table_matches_api():
    from plugins import detect
    table = detect.api_permissions(refresh=True)
    for method, perm in {"http_request": "network", "run": "shell", "system_info": "system", "add_shortcut": "ui",
                         "project_write_text": "files.write", "register_ai_tool": "ai.tools",
                         "clipboard_text": "clipboard", "set_theme": "ui"}.items():
        assert table[method] == perm, method
    assert "data_path" not in table and "log" not in table             # sans permission
