"""1.1.1 : dépendances entre plugins, libs Python par plugin (versions différentes), permissions détectées."""

import json
import sys

import plugins
import pytest
from plugins import deps, detect, pylibs
from plugins import manifest as m


@pytest.fixture
def pdir(isolated_data_dir):
    d = plugins.plugins_dir()
    d.mkdir(parents=True, exist_ok=True)
    yield d
    plugins.load_all()


def write(pdir, pid, code="def on_load(api):\n    pass\n", version="1.0.0", **extra):
    folder = pdir / pid
    folder.mkdir(exist_ok=True)
    manifest = {"id": pid, "name": pid, "version": version, "author": "t", "api": 5, "entry": "main.py",
                "permissions": [], **extra}
    (folder / "plugin.json").write_text(json.dumps(manifest))
    (folder / "main.py").write_text(code)
    return folder


# ── résolution ──
def test_resolve_order_and_problems():
    res = deps.resolve({"c": {"b": ">=1"}, "b": {"a": "*"}, "a": {}}, {"a": "1.0.0", "b": "1.2.0", "c": "1.0.0"})
    assert res.order == ["a", "b", "c"] and not res.problems
    res = deps.resolve({"x": {"manque": ">=1"}, "y": {"x": "*"}}, {"x": "1.0.0", "y": "1.0.0"})
    assert "manquante" in res.problems["x"] and "y" in res.problems and res.order == []
    res = deps.resolve({"p": {"q": ">=2"}, "q": {}}, {"p": "1.0.0", "q": "1.5.0"})
    assert "exige >=2" in res.problems["p"] and res.order == ["q"]
    res = deps.resolve({"a": {"b": "*"}, "b": {"a": "*"}}, {"a": "1.0.0", "b": "1.0.0"})
    assert any("circulaires" in v for v in res.problems.values())


def test_dependents_and_breaking_update():
    graph = {"a": {}, "b": {"a": ">=1,<2"}, "c": {"b": "*"}}
    assert deps.dependents("a", graph) == ["b", "c"] and deps.dependents("a", graph, transitive=False) == ["b"]
    assert deps.breaks_dependents("a", "2.0.0", graph) == ["b"] and deps.breaks_dependents("a", "1.9.0", graph) == []


def test_missing_for_install():
    catalog = {"api-plus": ("1.2.0", {}), "tool": ("1.0.0", {"api-plus": ">=1.0"})}
    order, problems = deps.missing_for_install({"tool": "*"}, {}, catalog)
    assert order == ["api-plus", "tool"] and not problems
    order, problems = deps.missing_for_install({"tool": "*"}, {"api-plus": "1.5.0"}, catalog)
    assert order == ["tool"]
    _o, problems = deps.missing_for_install({"inconnu": "*"}, {}, catalog)
    assert "introuvable" in problems[0]
    _o, problems = deps.missing_for_install({"api-plus": ">=3"}, {}, catalog)
    assert "propose 1.2.0" in problems[0]


# ── chargement ──
def test_dependency_loaded_first_and_provides(pdir):
    write(pdir, "zz-child", "def on_load(api):\n    api.log(api.plugin('aa-base')['hello']())\n    api.provide({'v': 2})\n",
          dependencies={"aa-base": ">=1.0.0"})
    write(pdir, "aa-base", "def on_load(api):\n    api.provide({'hello': lambda: 'salut'})\n")
    plugins.load_all()
    child, base = plugins.find("zz-child"), plugins.find("aa-base")
    assert base.loaded and child.loaded and "salut" in child.logs[-1] and child.exports == {"v": 2}


def test_missing_or_old_dependency_blocks_load(pdir):
    write(pdir, "needs", dependencies={"absent": "*"})
    write(pdir, "old", version="1.0.0")
    write(pdir, "strict", dependencies={"old": ">=2"})
    plugins.load_all()
    assert not plugins.find("needs").loaded and "manquante" in plugins.find("needs").error
    assert not plugins.find("strict").loaded and "exige >=2" in plugins.find("strict").error
    assert plugins.find("old").loaded


def test_disable_parent_unloads_children_and_enable_restores(pdir):
    write(pdir, "base")
    write(pdir, "kid", dependencies={"base": "*"})
    plugins.load_all()
    plugins.set_enabled("base", False)
    assert not plugins.find("kid").loaded and "désactivée" in plugins.find("kid").error
    plugins.set_enabled("base", True)
    assert plugins.find("base").loaded and plugins.find("kid").loaded and not plugins.find("kid").error


def test_plugin_must_declare_dependency_to_use_it(pdir):
    write(pdir, "base")
    write(pdir, "sneaky", "def on_load(api):\n    api.plugin('base')\n")
    plugins.load_all()
    assert "dependencies" in plugins.find("sneaky").error


def test_plugin_events(pdir):
    write(pdir, "aa-watcher", "def on_load(api):\n    api.on('on_plugin_loaded', lambda ctx: api.log(ctx.data['id']))\n")
    write(pdir, "other")
    plugins.load_all()
    assert any("other" in line for line in plugins.find("aa-watcher").logs)


# ── bibliothèques propres au plugin ──
def fake_lib(plugin_id, version):
    lib = pylibs.libs_dir(plugin_id)
    lib.mkdir(parents=True)
    (lib / "fakelib.py").write_text(f"VERSION = '{version}'\n")
    (lib / "fakelib-0.dist-info").mkdir()
    (lib / pylibs.STAMP).write_text(json.dumps({"fingerprint": pylibs._fingerprint([f"fakelib=={version}"])}))


def test_two_plugins_use_different_versions_of_same_lib(pdir):
    for pid, ver in (("one", "1.0"), ("two", "2.0")):
        fake_lib(pid, ver)
        write(pdir, pid, "import fakelib\nV = fakelib.VERSION\n\ndef on_load(api):\n    api.log(fakelib.VERSION)\n"
              "    api.on('on_open', lambda ctx: api.log('later ' + __import__('fakelib').VERSION))\n"
              if False else "import fakelib\n\ndef on_load(api):\n    api.log(fakelib.VERSION)\n",
              requires=[f"fakelib=={ver}"], permissions=["libs"])
    plugins.load_all()
    assert plugins.find("one").logs[-1].endswith("1.0") and plugins.find("two").logs[-1].endswith("2.0")
    assert "fakelib" not in sys.modules                                   # rien n'a fui dans Voktora


def test_scope_restores_host_modules(pdir):
    fake_lib("p", "9.9")
    import json as host_json
    lib = pylibs.libs_dir("p")
    (lib / "json.py").write_text("X = 1\n")                              # une lib qui masque un module de Voktora
    with pylibs.scope("p"):
        import json as shadow
        assert getattr(shadow, "X", None) == 1
    assert sys.modules["json"] is host_json


def test_requires_needs_libs_permission(pdir):
    write(pdir, "nolibs", requires=["rich>=13"])
    write(pdir, "rusty", permissions=[], lang="rust", entry="Cargo.toml")
    plugins.load_all()
    assert "libs" in plugins.find("nolibs").error


def test_requires_not_installed_starts_install_and_reports_failure(pdir, monkeypatch):
    calls = []
    monkeypatch.setattr(pylibs, "install", lambda pid, req, on_output=None, force=False: calls.append((pid, req))
                        or (_ for _ in ()).throw(pylibs.LibsError("échec simulé")))
    write(pdir, "needy", requires=["abc>=1"], permissions=["libs"])
    plugins.load_all()
    import time
    for _ in range(50):
        if calls and not plugins.find("needy").pending_libs:
            break
        time.sleep(0.05)
    assert calls == [("needy", ["abc>=1"])] and "échec simulé" in plugins.find("needy").error


def test_installer_refuses_without_tool(monkeypatch, isolated_data_dir):
    monkeypatch.setattr(pylibs, "installer", lambda: None)
    with pytest.raises(pylibs.LibsError, match="uv"):
        pylibs.install("x", ["rich"])


def test_real_install_with_uv_when_available(isolated_data_dir):
    """Installe vraiment une petite roue (si l'installateur et le réseau sont disponibles)."""
    if pylibs.installer() is None:
        pytest.skip("pas d'installateur")
    try:
        pylibs.install("real", ["six==1.16.0"])
    except pylibs.LibsError as exc:
        pytest.skip(f"réseau indisponible : {str(exc)[:80]}")
    assert pylibs.is_ready("real", ["six==1.16.0"])
    with pylibs.scope("real"):
        import six
        assert six.__version__ == "1.16.0"


# ── permissions détectées ──
def test_detect_python_permissions_from_code():
    code = ("import socket\nimport subprocess\n\ndef on_load(api):\n    api.http_get('https://x')\n"
            "    api.add_menu_action('a', 'b', print)\n    api.system_info()\n    api.set_clipboard_text('x')\n")
    found = detect.detect_python_source(code)
    assert found.permissions == {"network", "shell", "ui", "system", "clipboard"}
    assert any("api.http_get" in r for r in found.reasons["network"])


def test_detect_getattr_warns():
    found = detect.detect_python_source("def on_load(api):\n    getattr(api, 'http_get')('x')\n")
    assert found.warnings and not found.permissions


def test_detect_js_and_rust(tmp_path):
    assert detect.detect_js_source("voktora.httpGet('x');\nvoktora.addMenuAction('a','b',()=>{});").permissions == {"network", "ui"}
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text("use std::process::Command;\nfn f(api:&Api){ api.notify(\"x\"); api.http_get(\"u\"); }")
    (tmp_path / "Cargo.toml").write_text('[package]\nname="x"\n[dependencies]\nreqwest = "0.12"\nserde_json = "1"\n')
    found = detect.detect_folder(tmp_path, {"lang": "rust"})
    assert {"native", "shell", "network", "ui"} <= found.permissions


def test_auto_permissions_manifest_and_missing_report(pdir):
    folder = write(pdir, "auto", "import subprocess\n\ndef on_load(api):\n    api.http_get('https://x')\n", permissions="auto")
    data = json.loads((folder / "plugin.json").read_text())
    manifest, errors = m.validate(data)
    assert manifest.auto_permissions and not errors
    plugins.load_all()
    assert {"network", "shell"} <= set(plugins.find("auto").permissions)
    assert detect.missing_permissions(folder, ["shell"], data).keys() == {"network"}
    assert detect.unused_permissions(folder, ["shell", "network", "files"], data) == ["files"]


# ── marketplace : dépendances et mises à jour automatiques ──
def _entry(pid, version="1.0.0", perms=(), dependencies=None, **kw):
    from plugins import market
    return market.MarketEntry(id=pid, name=pid, version=version, author="a", permissions=list(perms),
                              dependencies=dependencies or {}, path=f"plugins/{pid}", **kw)


def test_index_rejects_auto_permissions_and_community_rust(isolated_data_dir):
    from plugins import market
    base = {"id": "x1", "name": "X", "version": "1.0.0", "author": "a", "files": {"plugin.json": "0" * 64, "main.py": "0" * 64}}
    with pytest.raises(market.MarketError, match="explicite"):
        market.parse_entry({**base, "permissions": "auto"})
    rust = {**base, "lang": "rust", "entry": "Cargo.toml", "permissions": ["native"], "tier": "community",
            "repo": "https://github.com/a/b", "commit": "a" * 40,
            "files": {"plugin.json": "0" * 64, "Cargo.toml": "0" * 64}}
    with pytest.raises(market.MarketError, match="natif"):
        market.parse_entry(rust)


def test_auto_update_rules(pdir, monkeypatch):
    from plugins import market
    for pid, extra in (("up", {}), ("perm", {}), ("parent", {}), ("kid", {"dependencies": {"parent": "<2"}})):
        folder = write(pdir, pid, **extra)
        (folder / ".source.json").write_text(json.dumps({"origin": "market", "files": {}}))
    plugins.load_all()
    for p in plugins.get_all():
        p.origin = "market"
    entries = [_entry("up", "1.1.0"), _entry("perm", "1.1.0", perms=["network"]), _entry("parent", "2.0.0"),
               _entry("kid", "1.0.0", dependencies={"parent": "<2"})]
    installed = []
    monkeypatch.setattr(market, "install", lambda e, base=None, on_progress=None: installed.append(e.id))
    report = market.auto_update(entries, force=True)
    assert report.updated == ["up"] and installed == ["up"]
    assert "network" in report.skipped["perm"] and "kid" in report.skipped["parent"]


def test_auto_update_off_and_throttled(isolated_data_dir, monkeypatch):
    from plugins import market
    market.set_auto_update(False)
    assert not market.auto_update([]).updated
    market.set_auto_update(True)
    market._stamp_update()
    assert not market._due()


def test_install_with_dependencies_order(pdir, monkeypatch):
    from plugins import market
    entries = [_entry("api-plus"), _entry("tool", dependencies={"api-plus": ">=1.0"})]
    installed = []
    monkeypatch.setattr(market, "install", lambda e, base=None, on_progress=None: installed.append(e.id))
    assert market.install_with_dependencies(entries[1], entries) == ["api-plus", "tool"] and installed == ["api-plus", "tool"]
    with pytest.raises(market.MarketError, match="introuvable"):
        market.install_with_dependencies(_entry("z", dependencies={"nope": "*"}), entries)
