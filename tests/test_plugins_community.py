"""Plugins communautaires : sous-modules épinglés, intégrité, garde d'imports, retrait, règles de PR."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "voktora"))
sys.path.insert(0, str(REPO / "tools"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import plugin_tool  # noqa: E402
import plugins  # noqa: E402
from plugins import (  # noqa: E402
    audit,
    lock,
    market,  # noqa: E402
)

COMMIT = "a" * 40
REPO_URL = "https://github.com/alice/cool-plugin"


def _manifest(plugin_id="cool", version="1.0.0", permissions=("ui",)):
    return {"id": plugin_id, "name": "Cool", "version": version, "author": "alice", "description": "d",
            "api": 2, "entry": "main.py", "permissions": list(permissions)}


def _entry(files: dict[str, bytes], **overrides):
    raw = {**_manifest(), "tier": "community", "repo": REPO_URL, "commit": COMMIT,
           "files": {n: hashlib.sha256(c).hexdigest() for n, c in files.items()}}
    raw.update(overrides)
    return market.parse_entry(raw)


def _files(code=b"def on_load(api):\n    pass\n", manifest=None):
    return {"plugin.json": json.dumps(manifest or _manifest()).encode(), "main.py": code}


@pytest.fixture
def pdir(isolated_data_dir):
    folder = plugins.plugins_dir()
    folder.mkdir(parents=True, exist_ok=True)
    return folder


@pytest.fixture
def raw_served(monkeypatch):
    """Sert des fichiers « GitHub » : {url: contenu}."""
    served: dict[str, bytes] = {}
    requested: list[str] = []

    def fake_fetch(url, timeout=0, limit=0):
        requested.append(url)
        if url not in served:
            raise market.MarketError("404")
        return served[url]

    monkeypatch.setattr(market, "_fetch", fake_fetch)
    return served, requested


def _serve(served, files, commit=COMMIT):
    for name, content in files.items():
        served[f"https://raw.githubusercontent.com/alice/cool-plugin/{commit}/{name}"] = content


class TestEntries:
    def test_community_entry_requires_repo_and_full_commit(self):
        files = _files()
        assert _entry(files).community and _entry(files).short_commit == "aaaaaaa"
        for bad in ({"repo": "http://github.com/a/b"}, {"repo": "https://evil.com/a/b"}, {"commit": "main"},
                    {"commit": "abc123"}, {"repo": "https://github.com/a/b/../../c"}):
            with pytest.raises(market.MarketError):
                _entry(files, **bad)

    def test_unknown_tier_rejected(self):
        with pytest.raises(market.MarketError):
            _entry(_files(), tier="weird")

    def test_download_url_is_pinned_to_commit(self):
        entry = _entry(_files())
        assert market.file_url(entry, "https://x", "main.py") == \
            f"https://raw.githubusercontent.com/alice/cool-plugin/{COMMIT}/main.py"

    def test_permission_changes(self):
        assert market.permission_changes(["ui"], ["ui", "network", "shell"]) == ["network", "shell"]
        assert market.permission_changes(["ui", "files"], ["ui"]) == []


class TestInstall:
    def test_install_writes_lock_and_loads(self, pdir, raw_served):
        served, requested = raw_served
        files = _files()
        _serve(served, files)
        folder = market.install(_entry(files), base="https://x")
        data = lock.read_lock(folder)
        assert data["origin"] == "market" and data["tier"] == "community" and data["commit"] == COMMIT
        assert set(data["files"]) == {"plugin.json", "main.py"} and lock.verify(folder, data) == []
        assert all(COMMIT in url for url in requested)
        info = plugins.load_all()[0]
        assert info.loaded and info.origin == "market" and info.repo == REPO_URL

    def test_audit_blocks_dangerous_code_at_install(self, pdir, raw_served):
        served, _ = raw_served
        files = _files(b"import subprocess\ndef on_load(api):\n    subprocess.run(['id'])\n")
        _serve(served, files)
        with pytest.raises(market.MarketError, match="sécurité"):
            market.install(_entry(files), base="https://x")
        assert not (pdir / "cool").exists()

    def test_tampered_download_rejected(self, pdir, raw_served):
        served, _ = raw_served
        files = _files()
        entry = _entry(files)
        _serve(served, {**files, "main.py": b"print('evil')\n"})
        with pytest.raises(market.MarketError, match="Empreinte"):
            market.install(entry, base="https://x")


class TestIntegrity:
    def _installed(self, pdir, raw_served, code=b"def on_load(api):\n    pass\n"):
        served, _ = raw_served
        files = _files(code)
        _serve(served, files)
        return market.install(_entry(files), base="https://x")

    def test_modified_file_is_not_executed(self, pdir, raw_served):
        folder = self._installed(pdir, raw_served)
        (folder / "main.py").write_text("open('/tmp/pwned','w')\ndef on_load(api):\n    pass\n", encoding="utf-8")
        info = plugins.load_all()[0]
        assert not info.loaded and "Intégrité" in info.error

    def test_added_file_blocks_loading(self, pdir, raw_served):
        folder = self._installed(pdir, raw_served)
        (folder / "extra.py").write_text("x = 1\n", encoding="utf-8")
        assert "Intégrité" in plugins.load_all()[0].error

    def test_deleted_file_blocks_loading(self, pdir, raw_served):
        folder = self._installed(pdir, raw_served)
        (folder / "plugin.json").unlink()
        assert not plugins.load_all()[0].loaded

    def test_lock_removal_does_not_bypass_guard_for_market_ids(self, pdir, raw_served):
        folder = self._installed(pdir, raw_served)
        data = lock.read_lock(folder)
        data["files"]["main.py"] = "0" * 64
        lock.write_lock(folder, data)
        assert not plugins.load_all()[0].loaded


class TestImportGuard:
    def _load(self, pdir, raw_served, code, extra=None, permissions=("ui",)):
        served, _ = raw_served
        files = {"plugin.json": json.dumps(_manifest(permissions=permissions)).encode(), "main.py": code}
        files.update(extra or {})
        _serve(served, files)
        market.install(_entry(files, permissions=list(permissions)), base="https://x")
        return plugins.load_all()[0]

    def test_computed_import_is_refused_at_install(self, pdir, raw_served):
        code = b"def on_load(api):\n    name = 'sub' + 'process'\n    m = __import__(name)\n"
        with pytest.raises(market.MarketError):
            self._load(pdir, raw_served, code)

    def test_loader_executes_plugin_with_guarded_builtins(self, pdir, raw_served):
        info = self._load(pdir, raw_served, b"def on_load(api):\n    pass\n")
        assert info.loaded
        module_builtins = sys.modules[info.module_name].__dict__["__builtins__"]
        assert "eval" not in module_builtins and "exec" not in module_builtins

    def test_guarded_builtins_have_no_eval_exec(self):
        safe = plugins.runtime._guarded_builtins(["ui"], "x")
        assert "eval" not in safe and "exec" not in safe and "compile" not in safe
        with pytest.raises(ImportError):
            safe["__import__"]("socket")
        with pytest.raises(ImportError):
            safe["__import__"]("urllib", fromlist=["request"])
        assert safe["__import__"]("json")

    def test_network_allowed_with_permission(self):
        safe = plugins.runtime._guarded_builtins(["ui", "network"], "x")
        assert safe["__import__"]("socket")



class TestRevocation:
    def test_revoked_plugin_is_unloaded_and_blocked(self, pdir, raw_served):
        served, _ = raw_served
        files = _files()
        _serve(served, files)
        market.install(_entry(files), base="https://x")
        assert plugins.load_all()[0].loaded
        plugins.runtime.revoked_path().parent.mkdir(parents=True, exist_ok=True)
        plugins.runtime.revoked_path().write_text(json.dumps([{"id": "cool", "reason": "malveillant"}]), encoding="utf-8")
        assert plugins.runtime.enforce_revocations() == ["cool"]
        info = plugins.find("cool")
        assert not info.loaded and "retiré" in info.error
        assert "retiré" in plugins.load_all()[0].error

    def test_revocation_can_target_one_commit(self, pdir, raw_served):
        served, _ = raw_served
        files = _files()
        _serve(served, files)
        market.install(_entry(files), base="https://x")
        plugins.runtime.revoked_path().parent.mkdir(parents=True, exist_ok=True)
        plugins.runtime.revoked_path().write_text(json.dumps([{"id": "cool", "commit": "b" * 40}]), encoding="utf-8")
        assert plugins.load_all()[0].loaded

    def test_parse_revoked_ignores_garbage(self):
        data = json.dumps({"revoked": [{"id": "ok", "reason": "x"}, {"id": "../bad"}, 5, {"id": 3}]}).encode()
        assert [r["id"] for r in market.parse_revoked(data)] == ["ok"]
        assert market.parse_revoked(b"not json") == []

    def test_fetch_index_stores_revocations(self, pdir, monkeypatch):
        index = {"schema": 1, "plugins": [], "revoked": [{"id": "bad", "reason": "r"}]}
        monkeypatch.setattr(market, "_fetch", lambda *a, **k: json.dumps(index).encode())
        market.fetch_index("https://x")
        assert plugins.runtime.revoked_entry("bad")["reason"] == "r"


class TestAudit:
    @pytest.mark.parametrize("code", [
        "import importlib\n", "import ctypes\n", "import builtins\n", "x = ().__class__.__bases__\n",
        "f = eval\nf('1')\n", "getattr(__builtins__, 'ex' + 'ec')\n", "import pickle\n", "exec('1')\n",
        "x = obj.__subclasses__()\n", "import os\nos.system('id')\n",
    ])
    def test_forbidden(self, tmp_path, code):
        path = tmp_path / "m.py"
        path.write_text(code, encoding="utf-8")
        assert audit.check_source(path, ["ui"])[0], code

    def test_clean_code_passes(self, tmp_path):
        path = tmp_path / "m.py"
        path.write_text("import json, re\nfrom pathlib import Path\ndef on_load(api):\n    pass\n", encoding="utf-8")
        assert audit.check_source(path, ["ui"]) == ([], [])

    def test_permission_unlocks_module(self, tmp_path):
        path = tmp_path / "m.py"
        path.write_text("import socket\n", encoding="utf-8")
        assert audit.check_source(path, ["ui"])[0] and not audit.check_source(path, ["ui", "network"])[0]

    def test_same_rules_in_tool_and_app(self):
        assert plugin_tool.audit.ALWAYS_DENIED == audit.ALWAYS_DENIED


# ── Règles de PR avec de vrais dépôts Git ─────────────────────────────────────────────────────────

def _git(cwd, *args, check=True):
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
    if check and result.returncode:
        raise AssertionError(result.stderr)
    return result.stdout.strip()


@pytest.fixture
def world(tmp_path, monkeypatch):
    """Dépôt « Voktora » + dépôt de plugin d'un contributeur, avec une URL https simulée par insteadOf."""
    gitconfig = tmp_path / "gitconfig"
    plugin_repo = tmp_path / "alice-plugin"
    gitconfig.write_text(f'[user]\n\tname = t\n\temail = t@t\n[protocol "file"]\n\tallow = always\n'
                         f'[url "{plugin_repo.as_posix()}"]\n\tinsteadOf = {REPO_URL}\n', encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    plugin_repo.mkdir()
    _git(plugin_repo, "init", "-q", "-b", "main")
    (plugin_repo / "plugin.json").write_text(json.dumps(_manifest()), encoding="utf-8")
    (plugin_repo / "main.py").write_text("def on_load(api):\n    pass\n", encoding="utf-8")
    (plugin_repo / "LICENSE").write_text("MIT", encoding="utf-8")
    _git(plugin_repo, "add", "-A")
    _git(plugin_repo, "commit", "-qm", "v1")

    main = tmp_path / "voktora"
    (main / "marketplace" / "plugins").mkdir(parents=True)
    _git(main, "init", "-q", "-b", "main")
    (main / "README.md").write_text("x", encoding="utf-8")
    _git(main, "add", "-A")
    _git(main, "commit", "-qm", "init")
    for name, value in {"ROOT": main, "MARKET": main / "marketplace", "PLUGINS": main / "marketplace" / "plugins",
                        "COMMUNITY": main / "marketplace" / "community", "INDEX": main / "marketplace" / "index.json",
                        "REVOKED": main / "marketplace" / "revoked.json", "GITMODULES": main / ".gitmodules"}.items():
        monkeypatch.setattr(plugin_tool, name, value)
    return main, plugin_repo


def _add_submodule(main):
    _git(main, "submodule", "add", "-q", REPO_URL, "marketplace/community/cool")
    _git(main, "add", "-A")
    _git(main, "commit", "-qm", "add plugin")


class TestPullRequestRules:
    def test_valid_submission_and_index(self, world):
        main, _ = world
        _git(main, "branch", "base", "HEAD")
        _add_submodule(main)
        assert plugin_tool.check_pr("base") == []
        errors, warnings = plugin_tool.validate_plugin(main / "marketplace" / "community" / "cool")
        assert errors == [], errors
        index = plugin_tool.build_index()
        entry = index["plugins"][0]
        pinned = plugin_tool.pinned_commit("marketplace/community/cool")
        assert entry["tier"] == "community" and entry["repo"] == REPO_URL and entry["commit"] == pinned
        assert set(entry["files"]) == {"plugin.json", "main.py"}          # LICENSE jamais publié
        assert "path" not in entry
        assert market.parse_entry(entry).commit == pinned

    def test_code_change_requires_new_pr_even_after_acceptance(self, world):
        main, plugin_repo = world
        _add_submodule(main)
        _git(main, "branch", "base", "HEAD")                      # état accepté
        pinned = plugin_tool.pinned_commit("marketplace/community/cool")
        # l'auteur modifie son dépôt : rien ne bouge dans l'index tant qu'aucune PR n'est fusionnée
        (plugin_repo / "main.py").write_text("import os\ndef on_load(api):\n    pass\n", encoding="utf-8")
        _git(plugin_repo, "commit", "-qam", "v2 sneaky")
        assert plugin_tool.build_index()["plugins"][0]["commit"] == pinned
        # la dérive est détectée
        assert plugin_tool.cmd_drift(type("A", (), {"fail": True})()) == 1
        # nouvelle PR : pin bump SANS incrémenter la version → refusé
        sub = main / "marketplace" / "community" / "cool"
        _git(sub, "pull", "-q", "origin", "main")
        _git(main, "add", "-A")
        _git(main, "commit", "-qm", "bump")
        assert plugin_tool.cmd_check_pr(type("A", (), {"base": "base"})()) == 1
        assert plugin_tool.build_index()["plugins"][0]["commit"] != pinned

    def test_version_bump_passes(self, world):
        main, plugin_repo = world
        _add_submodule(main)
        _git(main, "branch", "base", "HEAD")
        (plugin_repo / "plugin.json").write_text(json.dumps(_manifest(version="1.1.0")), encoding="utf-8")
        _git(plugin_repo, "commit", "-qam", "v1.1")
        sub = main / "marketplace" / "community" / "cool"
        _git(sub, "pull", "-q", "origin", "main")
        _git(main, "add", "-A")
        _git(main, "commit", "-qm", "bump")
        assert plugin_tool.cmd_check_pr(type("A", (), {"base": "base"})()) == 0

    def test_pr_cannot_touch_other_files(self, world):
        main, _ = world
        _git(main, "branch", "base", "HEAD")
        _add_submodule(main)
        (main / "voktora_evil.py").write_text("x", encoding="utf-8")
        _git(main, "add", "-A")
        _git(main, "commit", "-qm", "sneaky")
        assert any("en trop" in e for e in plugin_tool.check_pr("base"))

    def test_gitmodules_with_extra_keys_rejected(self, world):
        main, _ = world
        _git(main, "branch", "base", "HEAD")
        _add_submodule(main)
        _git(main, "config", "--file", ".gitmodules", "submodule.marketplace/community/cool.branch", "main")
        _git(main, "add", "-A")
        _git(main, "commit", "-qm", "evil")
        assert any("interdites" in e for e in plugin_tool.check_pr("base"))

    @pytest.mark.parametrize("url", ["git@github.com:a/b.git", "file:///etc", "https://evil.example/a/b",
                                     "https://user:pw@github.com/a/b", "http://github.com/a/b",
                                     "https://github.com/a/b.git"])
    def test_non_github_https_urls_rejected(self, world, url):
        main, _ = world
        _git(main, "branch", "base", "HEAD")
        _add_submodule(main)
        _git(main, "config", "--file", ".gitmodules", "submodule.marketplace/community/cool.url", url)
        _git(main, "add", "-A")
        _git(main, "commit", "-qm", "url")
        assert plugin_tool.check_pr("base")

    def test_dangerous_code_in_submodule_fails_validation(self, world):
        main, plugin_repo = world
        (plugin_repo / "main.py").write_text("import subprocess\ndef on_load(api):\n    pass\n", encoding="utf-8")
        _git(plugin_repo, "commit", "-qam", "bad")
        _add_submodule(main)
        errors, _ = plugin_tool.validate_plugin(main / "marketplace" / "community" / "cool")
        assert any("subprocess" in e for e in errors)

    def test_unpinned_checkout_fails(self, world):
        main, plugin_repo = world
        _add_submodule(main)
        (plugin_repo / "x.txt").write_text("x", encoding="utf-8")
        _git(plugin_repo, "add", "-A")
        _git(plugin_repo, "commit", "-qm", "later")
        sub = main / "marketplace" / "community" / "cool"
        _git(sub, "pull", "-q", "origin", "main")               # HEAD avancé mais pin inchangé
        errors, _ = plugin_tool.validate_plugin(sub)
        assert any("épinglé" in e for e in errors)

    def test_submit_command(self, world):
        main, _ = world
        code = plugin_tool.main(["submit", REPO_URL, "--id", "cool"])
        assert code == 0 and (main / "marketplace" / "community" / "cool" / "plugin.json").is_file()
        assert plugin_tool.main(["submit", "git@github.com:a/b.git"]) == 2
