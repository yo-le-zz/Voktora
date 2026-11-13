"""Plugins 1.0.6 : manifeste, API, permissions, chargement, activation, marketplace, interface."""

import hashlib
import json
import os
import sys
import zipfile
from pathlib import Path
from typing import ClassVar

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "voktora"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import plugins  # noqa: E402
from plugins import manifest as mf  # noqa: E402
from plugins import market  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
MARKET_DIR = REPO / "marketplace"


def _write_plugin(root: Path, plugin_id: str, code: str, permissions=("ui",), version="1.0.0", legacy=False):
    if legacy:
        (root / f"{plugin_id}.py").write_text(code, encoding="utf-8")
        return root / f"{plugin_id}.py"
    folder = root / plugin_id
    folder.mkdir(parents=True)
    (folder / "plugin.json").write_text(json.dumps({
        "id": plugin_id, "name": plugin_id.title(), "version": version, "author": "test",
        "description": "d", "api": 2, "entry": "main.py", "permissions": list(permissions)}), encoding="utf-8")
    (folder / "main.py").write_text(code, encoding="utf-8")
    return folder


@pytest.fixture
def pdir(isolated_data_dir):
    folder = plugins.plugins_dir()
    folder.mkdir(parents=True, exist_ok=True)
    plugins.set_ui_host(None)
    yield folder
    plugins.set_ui_host(None)
    plugins.load_all()


# ── Manifeste ────────────────────────────────────────────────────────────────────

class TestManifest:
    GOOD: ClassVar[dict] = {"id": "my-plugin", "name": "My", "version": "1.2.3", "author": "me"}

    def test_valid_minimal_manifest(self):
        parsed, errors = mf.validate(self.GOOD)
        assert not errors and parsed.entry == "main.py" and parsed.api == mf.API_VERSION

    @pytest.mark.parametrize("patch,fragment", [
        ({"id": "Bad_ID"}, "id"),
        ({"id": ""}, "obligatoire"),
        ({"version": "1.0"}, "version"),
        ({"author": ""}, "author"),
        ({"api": 99}, "API 99"),
        ({"entry": "../evil.py"}, "entry"),
        ({"entry": "/abs.py"}, "entry"),
        ({"entry": "main.txt"}, "entry"),
        ({"permissions": ["root"]}, "inconnue"),
        ({"permissions": "ui"}, "permissions"),
        ({"homepage": "http://x"}, "https"),
        ({"tags": ["a"] * 9}, "tags"),
        ({"description": "x" * 500}, "trop long"),
    ])
    def test_invalid_manifests(self, patch, fragment):
        parsed, errors = mf.validate({**self.GOOD, **patch})
        assert parsed is None and any(fragment in e for e in errors)

    def test_not_an_object(self):
        assert mf.validate([1])[0] is None

    def test_version_compare(self):
        assert mf.is_newer("1.0.10", "1.0.9") and not mf.is_newer("1.0.0", "1.0.0")
        assert mf.version_tuple("v2.1-beta") == (2, 1, 0) and mf.version_tuple("???") == (0, 0, 0)

    def test_load_errors_are_explicit(self, tmp_path):
        with pytest.raises(mf.ManifestError, match="introuvable"):
            mf.load(tmp_path)
        (tmp_path / "plugin.json").write_text("{nope", encoding="utf-8")
        with pytest.raises(mf.ManifestError, match="JSON"):
            mf.load(tmp_path)


# ── Chargement, API, permissions ───────────────────────────────────────────────────────

class TestRuntime:
    def test_folder_plugin_loads_and_registers(self, pdir):
        _write_plugin(pdir, "hello", (
            "def on_load(api):\n"
            "    api.register_command('c', lambda ctx: None, desc='d')\n"
            "    api.register_button('B', lambda ctx: None)\n"
            "    api.register_hook('on_open', lambda ctx: ctx.log('opened ' + ctx.project_path.name))\n"))
        plugins.load_all()
        info = plugins.find("hello")
        assert info.loaded and not info.error and info.version == "1.0.0"
        assert [c.name for _p, c in plugins.all_commands()] == ["c"]
        assert len(plugins.all_buttons()) == 1
        logs: list[str] = []
        plugins.fire_hook("on_open", Path("/x/proj"), log_cb=logs.append)
        assert logs == ["opened proj"]

    def test_legacy_single_file_plugin_still_works(self, pdir):
        _write_plugin(pdir, "old", (
            "PLUGIN_NAME='Old'\nPLUGIN_VERSION='0.3'\nPLUGIN_AUTHOR='a'\n"
            "def on_load(api):\n    api.register_button('X', lambda ctx: None)\n"), legacy=True)
        plugins.load_all()
        info = plugins.find("old")
        assert info.legacy and info.loaded and (info.name, info.version) == ("Old", "0.3")

    def test_underscore_and_dot_entries_are_ignored(self, pdir):
        _write_plugin(pdir, "_skip", "x = 1", legacy=True)
        (pdir / ".hidden").mkdir()
        plugins.load_all()
        assert plugins.get_all() == []

    def test_broken_plugin_is_reported_not_raised(self, pdir):
        _write_plugin(pdir, "broken", "raise RuntimeError('boom')")
        _write_plugin(pdir, "fine", "def on_load(api):\n    api.register_button('ok', lambda c: None)\n")
        plugins.load_all()
        assert "boom" in plugins.find("broken").error and not plugins.find("broken").loaded
        assert plugins.find("fine").loaded

    def test_invalid_manifest_is_reported(self, pdir):
        folder = pdir / "nomani"
        folder.mkdir()
        (folder / "main.py").write_text("", encoding="utf-8")
        plugins.load_all()
        assert "plugin.json" in plugins.find("nomani").error

    def test_failing_hook_does_not_affect_others(self, pdir):
        _write_plugin(pdir, "bad", "def on_load(api):\n    api.on('on_open', lambda c: 1/0)\n")
        _write_plugin(pdir, "good", "def on_load(api):\n    api.on('on_open', lambda c: c.log('good'))\n")
        plugins.load_all()
        logs: list[str] = []
        plugins.fire_hook("on_open", log_cb=logs.append)
        assert "good" in logs and any("bad" in line.lower() for line in logs)
        assert plugins.find("bad").errors

    def test_unknown_event_is_rejected(self, pdir):
        _write_plugin(pdir, "ev", "def on_load(api):\n    api.on('on_nothing', lambda c: None)\n")
        plugins.load_all()
        assert "Événement inconnu" in plugins.find("ev").error

    def test_plugin_to_plugin_events(self, pdir):
        _write_plugin(pdir, "a", "def on_load(api):\n    api.on('plugin:ping', lambda c: c.log('pong ' + str(c.data['n'])))\n"
                      "    api.register_command('go', lambda ctx: api.emit('ping', n=3))\n")
        plugins.load_all()
        logs: list[str] = []
        plugins.fire_hook("plugin:ping", log_cb=logs.append, data={"n": 3})
        assert logs == ["pong 3"]

    def test_permissions_are_enforced(self, pdir):
        code = (
            "def on_load(api):\n"
            "    for name, call in (('projects', lambda: api.projects()), ('net', lambda: api.http_get('https://x.y')),\n"
            "                       ('shell', lambda: api.run(['true'])), ('ui', lambda: api.notify('x'))):\n"
            "        try:\n            call()\n        except Exception as exc:\n"
            "            api.settings.set(name, type(exc).__name__ + ':' + str(exc))\n")
        _write_plugin(pdir, "noperm", code, permissions=())
        plugins.load_all()
        stored = plugins.PluginSettings("noperm").all()
        assert set(stored) == {"projects", "net", "shell", "ui"}
        assert all(v.startswith("PluginError") and "permission" in v for v in stored.values())

    def test_declared_permissions_work(self, pdir):
        code = ("def on_load(api):\n"
                "    code, out = api.run(['python3', '-c', 'print(42)'])\n"
                "    api.settings.set('out', [code, out.strip(), len(api.projects())])\n")
        _write_plugin(pdir, "perm", code, permissions=("shell", "projects.read"))
        plugins.load_all()
        assert plugins.PluginSettings("perm").get("out") == [0, "42", 0]

    def test_run_rejects_non_list_commands(self, pdir):
        code = ("def on_load(api):\n    try:\n        api.run('ls -la')\n    except Exception as e:\n"
                "        api.settings.set('e', str(e))\n")
        _write_plugin(pdir, "shellstr", code, permissions=("shell",))
        plugins.load_all()
        assert "liste" in plugins.PluginSettings("shellstr").get("e")

    def test_http_get_only_https(self, pdir):
        code = ("def on_load(api):\n    try:\n        api.http_get('http://example.com')\n    except Exception as e:\n"
                "        api.settings.set('e', str(e))\n")
        _write_plugin(pdir, "net", code, permissions=("network",))
        plugins.load_all()
        assert "https" in plugins.PluginSettings("net").get("e")

    def test_disable_enable_persists_and_does_not_run_code(self, pdir):
        _write_plugin(pdir, "t", "def on_load(api):\n    api.register_button('B', lambda c: None)\n"
                      "    api.settings.set('loads', api.settings.get('loads', 0) + 1)\n")
        plugins.load_all()
        assert plugins.PluginSettings("t").get("loads") == 1
        plugins.set_enabled("t", False)
        assert "t" in plugins.disabled_ids() and plugins.all_buttons() == []
        plugins.load_all()                       # rechargement complet : toujours désactivé, code non exécuté
        assert not plugins.find("t").loaded and plugins.PluginSettings("t").get("loads") == 1
        plugins.set_enabled("t", True)
        assert plugins.find("t").loaded and plugins.PluginSettings("t").get("loads") == 2

    def test_settings_roundtrip_and_isolation(self, pdir):
        a, b = plugins.PluginSettings("one"), plugins.PluginSettings("two")
        a.set("k", {"x": [1, 2]})
        assert a.get("k") == {"x": [1, 2]} and b.get("k") is None and a.get("zz", 5) == 5
        a.delete("k")
        assert a.all() == {}

    def test_stylesheet_and_theme_registration(self, pdir):
        class Host:
            restyled = 0

            def restyle(self):
                Host.restyled += 1

        plugins.set_ui_host(Host())
        _write_plugin(pdir, "skin", (
            "def on_load(api):\n    api.set_stylesheet('QPushButton { color: red; }')\n"
            "    api.register_theme('x', 'Skin X', {'base': '#101010', 'text': '#fefefe'})\n"))
        plugins.load_all()
        assert "color: red" in plugins.extra_stylesheet()
        assert "skin-x" in plugins.extra_themes()
        import theme_manager
        assert "skin-x" in theme_manager.get_available_themes()
        assert theme_manager.load_theme("skin-x")["colors"]["base"] == "#101010"
        plugins.set_enabled("skin", False)
        assert plugins.extra_stylesheet() == "" and "skin-x" not in plugins.extra_themes()
        assert Host.restyled >= 1

    def test_slow_handlers_are_flagged(self, pdir, monkeypatch):
        _write_plugin(pdir, "slow", "import time\ndef on_load(api):\n    api.on('on_open', lambda c: time.sleep(0.05))\n")
        plugins.load_all()
        monkeypatch.setattr(plugins.runtime, "SLOW_HANDLER_SECONDS", 0.01)
        plugins.fire_hook("on_open")
        assert plugins.find("slow").slow

    def test_unload_runs_on_unload(self, pdir):
        _write_plugin(pdir, "bye", "def on_load(api):\n    pass\ndef on_unload(api):\n    api.settings.set('bye', 1)\n")
        plugins.load_all()
        plugins.set_enabled("bye", False)
        assert plugins.PluginSettings("bye").get("bye") == 1


# ── Marketplace ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def served(monkeypatch):
    """Sert le dossier marketplace/ du dépôt à la place d'Internet."""
    requested: list[str] = []

    def fake_fetch(url, timeout=0, limit=0):
        requested.append(url)
        prefix = market.DEFAULT_URL + "/"
        assert url.startswith(prefix)
        path = MARKET_DIR / url[len(prefix):]
        if not path.is_file():
            raise market.MarketError("404")
        return path.read_bytes()

    monkeypatch.setattr(market, "_fetch", fake_fetch)
    return requested


class TestMarket:
    def test_repo_index_is_valid_and_up_to_date(self):
        entries = market.parse_index((MARKET_DIR / "index.json").read_bytes())
        assert len(entries) >= 7 and all(e.compatible for e in entries)
        import subprocess
        done = subprocess.run([sys.executable, str(REPO / "tools" / "plugin_tool.py"), "build-index", "--check"],
                              capture_output=True, text=True, check=False)
        assert done.returncode == 0, done.stdout + done.stderr

    def test_fetch_install_load_update_uninstall(self, pdir, served):
        entries, cached = market.fetch_index()
        assert not cached
        entry = next(e for e in entries if e.id == "project-counter")
        assert market.status(entry) == "new"
        progress: list[tuple] = []
        folder = market.install(entry, on_progress=lambda d, t, n: progress.append((d, t, n)))
        assert (folder / "main.py").is_file() and (folder / ".source.json").is_file()
        assert progress[-1][0] == progress[-1][1] == 2
        plugins.load_all()
        assert plugins.find("project-counter").origin == "market" and market.status(entry) == "installed"
        # version supérieure dans l'index -> « update »
        newer = market.MarketEntry(**{**entry.__dict__, "version": "9.0.0"})
        assert market.status(newer) == "update"
        assert market.uninstall("project-counter", purge_data=True)
        assert not (pdir / "project-counter").exists() and market.installed_version("project-counter") is None

    def test_tampered_file_is_rejected_and_nothing_installed(self, pdir, monkeypatch, served):
        entries, _ = market.fetch_index()
        entry = next(e for e in entries if e.id == "ui-tweaks")
        real = market._fetch

        def tampered(url, timeout=0, limit=0):
            data = real(url)
            return data + b"\n# injected" if url.endswith("main.py") else data

        monkeypatch.setattr(market, "_fetch", tampered)
        with pytest.raises(market.MarketError, match="Empreinte incorrecte"):
            market.install(entry)
        assert not (pdir / "ui-tweaks").exists()
        assert not any(p.name.startswith(".installing") for p in pdir.iterdir())

    def test_failed_update_keeps_previous_version(self, pdir, monkeypatch, served):
        entries, _ = market.fetch_index()
        entry = next(e for e in entries if e.id == "ui-tweaks")
        market.install(entry)
        monkeypatch.setattr(market, "_fetch", lambda *a, **k: (_ for _ in ()).throw(market.MarketError("offline")))
        with pytest.raises(market.MarketError):
            market.install(entry)
        assert (pdir / "ui-tweaks" / "main.py").is_file()

    def test_manifest_must_match_index(self, pdir, served):
        entries, _ = market.fetch_index()
        entry = next(e for e in entries if e.id == "ui-tweaks")
        lying = market.MarketEntry(**{**entry.__dict__, "permissions": ["ui", "shell"]})
        with pytest.raises(market.MarketError, match="ne correspond pas"):
            market.install(lying)

    def test_offline_uses_cache(self, pdir, served, monkeypatch):
        market.fetch_index()
        monkeypatch.setattr(market, "_fetch", lambda *a, **k: (_ for _ in ()).throw(market.MarketError("offline")))
        entries, cached = market.fetch_index()
        assert cached and len(entries) >= 7
        with pytest.raises(market.MarketError):
            market.fetch_index(use_cache_on_error=False)

    def test_https_required(self):
        with pytest.raises(market.MarketError, match="https"):
            market._fetch("http://example.com/index.json")
        with pytest.raises(market.MarketError, match="https"):
            market._fetch("file:///etc/passwd")

    @pytest.mark.parametrize("name", ["../x.py", "/abs.py", "a/../b.py", "a\\b.py", "evil.exe", "x.sh", "", ".hidden.py",
                                       "a" * 120 + ".py", "sp ace.py"])
    def test_unsafe_file_names_are_rejected(self, name):
        with pytest.raises(market.MarketError):
            market.safe_relative(name)

    def test_safe_names_pass(self):
        assert market.safe_relative("sub/helper.py") == "sub/helper.py"

    def test_broken_index_entries_are_skipped(self):
        good = json.loads((MARKET_DIR / "index.json").read_text(encoding="utf-8"))["plugins"][0]
        bad = {**good, "id": "evil", "files": {"../../x.py": "0" * 64, "plugin.json": "0" * 64, "main.py": "0" * 64}}
        data = json.dumps({"schema": 1, "plugins": [bad, good, "junk"]}).encode()
        assert [e.id for e in market.parse_index(data)] == [good["id"]]

    def test_unknown_schema_is_refused(self):
        with pytest.raises(market.MarketError, match="format"):
            market.parse_index(json.dumps({"schema": 99, "plugins": []}).encode())

    def test_incompatible_entry_is_refused(self, pdir, served):
        entries, _ = market.fetch_index()
        entry = market.MarketEntry(**{**entries[0].__dict__, "api": 99})
        with pytest.raises(market.MarketError, match="plus récente"):
            market.install(entry)

    def test_install_from_zip_and_folder(self, pdir, tmp_path):
        src = _write_plugin(tmp_path / "src_root_ignored" if False else tmp_path, "zipped",
                            "def on_load(api):\n    api.register_button('Z', lambda c: None)\n")
        archive = tmp_path / "zipped.zip"
        with zipfile.ZipFile(archive, "w") as z:
            for f in src.iterdir():
                z.write(f, f"zipped/{f.name}")          # avec dossier racine : accepté
        assert market.read_local_manifest(archive).id == "zipped"
        plugin_id, _folder = market.install_from_path(archive)
        plugins.load_all()
        assert plugin_id == "zipped" and plugins.find("zipped").loaded
        market.uninstall("zipped")
        plugin_id, _ = market.install_from_path(src)
        assert plugin_id == "zipped"

    def test_zip_slip_and_bad_archives_are_refused(self, pdir, tmp_path):
        evil = tmp_path / "evil.zip"
        with zipfile.ZipFile(evil, "w") as z:
            z.writestr("../../outside.py", "x")
            z.writestr("plugin.json", "{}")
        with pytest.raises(market.MarketError):
            market.install_from_path(evil)
        not_zip = tmp_path / "x.zip"
        not_zip.write_text("nope")
        with pytest.raises(market.MarketError):
            market.install_from_path(not_zip)
        assert not (tmp_path.parent / "outside.py").exists()

    def test_uninstall_rejects_bad_ids(self, pdir):
        with pytest.raises(market.MarketError):
            market.uninstall("../..")
        assert market.uninstall("not-installed") is False

    def test_sha_in_index_matches_files(self):
        for entry in market.parse_index((MARKET_DIR / "index.json").read_bytes()):
            for name, digest in entry.files.items():
                assert hashlib.sha256((MARKET_DIR / entry.path / name).read_bytes()).hexdigest() == digest


# ── Outil de validation (CI) ────────────────────────────────────────────────────────────────────

class TestPluginTool:
    @pytest.fixture
    def tool(self, monkeypatch, tmp_path):
        sys.path.insert(0, str(REPO / "tools"))
        import plugin_tool
        monkeypatch.setattr(plugin_tool, "PLUGINS", tmp_path / "plugins")
        (tmp_path / "plugins").mkdir()
        return plugin_tool

    def test_repo_plugins_pass_validation(self):
        sys.path.insert(0, str(REPO / "tools"))
        import plugin_tool
        assert plugin_tool.main(["validate"]) == 0

    @pytest.mark.parametrize("code,fragment", [
        ("import subprocess\n", "shell"),
        ("import urllib.request\n", "network"),
        ("eval('1')\n", "eval"),
        ("import os\nos.system('ls')\n", "os.system"),
        ("import subprocess\nsubprocess.run('x', shell=True)\n", "shell=True"),
        ("def broken(:\n", "illisible"),
    ])
    def test_dangerous_code_is_rejected(self, tool, tmp_path, code, fragment):
        _write_plugin(tmp_path / "plugins", "risky", code, permissions=("ui",))
        errors, _ = tool.validate_plugin(tmp_path / "plugins" / "risky")
        assert any(fragment in e for e in errors)

    def test_declared_permission_allows_import(self, tool, tmp_path):
        _write_plugin(tmp_path / "plugins", "ok", "import subprocess\n", permissions=("ui", "shell"))
        assert tool.validate_plugin(tmp_path / "plugins" / "ok")[0] == []

    def test_id_must_match_folder_and_files_are_checked(self, tool, tmp_path):
        folder = _write_plugin(tmp_path / "plugins", "folder-name", "x = 1\n")
        data = json.loads((folder / "plugin.json").read_text(encoding="utf-8"))
        data["id"] = "other"
        (folder / "plugin.json").write_text(json.dumps(data), encoding="utf-8")
        (folder / "run.sh").write_text("echo", encoding="utf-8")
        errors, _ = tool.validate_plugin(folder)
        assert any("identique" in e for e in errors) and any("non autorisé" in e for e in errors)

    def test_new_scaffold_validates(self, tool, tmp_path):
        assert tool.main(["new", "my-new", "--author", "me"]) == 0
        assert tool.validate_plugin(tmp_path / "plugins" / "my-new")[0] == []
        assert tool.main(["new", "my-new"]) == 2 and tool.main(["new", "Bad Id"]) == 2

    def test_zip_command(self, tool, tmp_path):
        tool.main(["new", "zz"])
        out = tmp_path / "zz.zip"
        assert tool.main(["zip", "zz", "--out", str(out)]) == 0
        assert market.read_local_manifest(out).id == "zz"
