"""DevOps Center : Git réel (dépôt temporaire), Docker/SSH/GitHub avec exécuteur simulé, pipelines, déploiements + restauration."""

import importlib
import subprocess
import sys
import threading
import types
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent / "marketplace" / "plugins" / "devops-center"


@pytest.fixture(scope="module")
def dc():
    pkg = types.ModuleType("devops_center")
    pkg.__path__ = [str(PLUGIN)]
    sys.modules["devops_center"] = pkg
    yield
    for n in [n for n in sys.modules if n == "devops_center" or n.startswith("devops_center.")]:
        del sys.modules[n]


def mod(n):
    return importlib.import_module("devops_center." + n)


def runner(args, cwd=None, timeout=60, env=None, cancel=None, on_line=None):
    return mod("core.proc").run(args, cwd=cwd, timeout=timeout, env=env, cancel=cancel, on_line=on_line)


def sh(cwd, *args):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    sh(r, "git", "init", "-q", "-b", "main")
    sh(r, "git", "config", "user.email", "t@t")
    sh(r, "git", "config", "user.name", "T")
    (r / "a.txt").write_text("1\n")
    sh(r, "git", "add", ".")
    sh(r, "git", "commit", "-qm", "premier")
    return r


def test_proc_stream_timeout_cancel(dc):
    p = mod("core.proc")
    lines = []
    r = p.run([sys.executable, "-c", "print('a');print('b')"], on_line=lines.append)
    assert r.ok and lines == ["a", "b"]
    assert p.run([sys.executable, "-c", "import time;time.sleep(5)"], timeout=0.3).timed_out
    ev = threading.Event()
    threading.Timer(0.3, ev.set).start()
    assert p.run([sys.executable, "-c", "import time;time.sleep(5)"], cancel=ev).cancelled
    assert not p.run(["programme-inexistant-zz"]).ok
    assert not p.run("pas une liste").ok


def test_git_status_branches_log_diff(dc, repo):
    g = mod("core.git").Git(repo, runner)
    assert g.is_repo() and g.status().clean and g.status().branch == "main"
    (repo / "a.txt").write_text("2\n")
    (repo / "new.txt").write_text("x")
    st = g.status()
    assert st.changed == [("M", "a.txt")] and st.untracked == ["new.txt"] and not st.clean
    assert "+2" in g.diff("a.txt")
    sh(repo, "git", "checkout", "-q", "-b", "feat")
    assert {b["name"] for b in g.branches()} == {"main", "feat"} and [b for b in g.branches() if b["current"]][0]["name"] == "feat"
    assert g.log()[0]["subject"] == "premier"
    g.checkout("main")
    assert g.status().branch == "main"
    with pytest.raises(mod("core.git").GitError):
        g.checkout("--evil")
    with pytest.raises(mod("core.git").GitError):
        g.pull()  # modifications locales


def test_git_has_no_push(dc):
    assert not hasattr(mod("core.git").Git, "push")
    src = (PLUGIN / "core" / "git.py").read_text()
    assert '"push"' not in src


def test_git_pull_and_fetch(dc, repo, tmp_path):
    clone = tmp_path / "clone"
    sh(tmp_path, "git", "clone", "-q", str(repo), str(clone))
    (repo / "b.txt").write_text("b")
    sh(repo, "git", "add", ".")
    sh(repo, "git", "commit", "-qm", "deux")
    g = mod("core.git").Git(clone, runner)
    g.fetch()
    assert g.status().behind == 1
    g.pull()
    assert (clone / "b.txt").exists() and g.status().behind == 0
    assert mod("core.github").parse_remote("git@github.com:yo-le-zz/Voktora.git") == ("yo-le-zz", "Voktora")
    assert mod("core.github").parse_remote("https://github.com/a/b") == ("a", "b")


def test_github_api_and_cli(dc):
    gh = mod("core.github")
    seen = {}

    def http(method, url, headers):
        seen.update(url=url, headers=headers)
        import json
        return 200, json.dumps([{"number": 1, "title": "t", "state": "open", "user": {"login": "u"}, "html_url": "h"},
                                {"number": 2, "title": "pr", "state": "open", "user": {"login": "u"}, "html_url": "h2", "pull_request": {}}]).encode()
    c = gh.GitHub(http=http, token=lambda: "tok")
    assert [i["number"] for i in c.issues("o", "r")] == [1]
    assert seen["headers"]["Authorization"] == "Bearer tok" and "/repos/o/r/issues" in seen["url"]
    with pytest.raises(gh.GitHubError):
        gh.GitHub(http=lambda *a: (404, b"")).issues("o", "r")
    R = mod("core.proc").Result
    cli = gh.GitHub(runner=lambda a, timeout=60: R(0, '[{"number":3,"title":"x","state":"OPEN","author":{"login":"z"},"url":"u"}]'))
    assert cli.issues("o", "r", prefer_cli=True)[0]["state"] == "open"


def test_docker_parsing_and_validation(dc):
    d, R = mod("core.docker"), mod("core.proc").Result
    calls = []

    def fake(args, cwd=None, timeout=60):
        calls.append(args)
        if args[1] == "ps":
            return R(0, '{"ID":"1","Names":"web","Image":"nginx","Status":"Up","State":"running","Ports":"80"}\n')
        return R(0, "ok")
    dk = d.Docker(fake)
    assert dk.containers()[0]["name"] == "web"
    dk.action("stop", "web")
    assert calls[-1] == ["docker", "stop", "web"]
    with pytest.raises(d.DockerError):
        dk.action("stop", "--all; rm")
    with pytest.raises(d.DockerError):
        dk.action("exec", "web")
    dk.compose("up")
    assert calls[-1][:3] == ["docker", "compose", "up"] and "-d" in calls[-1]


def test_ssh_args_safe(dc):
    s = mod("core.ssh")
    p = s.SSHProfile("srv", "example.org", "deploy", 2222, "/k/id")
    a = s.ssh_args(p, "uptime")
    assert a[0] == "ssh" and "BatchMode=yes" in a and a[-3:] == ["--", "deploy@example.org", "uptime"] and "2222" in a
    assert s.scp_args(p, "/l", "/r", True, True)[:2] == ["scp", "-r"]
    for bad in (s.SSHProfile("x", "-oProxyCommand=evil"), s.SSHProfile("x", "h", "u v"), s.SSHProfile("x", "h", port=0)):
        with pytest.raises(ValueError):
            bad.validate()


def test_pipeline_conditions_retries_cancel(dc, tmp_path):
    pl = mod("core.pipeline")
    py = sys.executable
    flag = tmp_path / "n"
    flaky = f"{py} -c \"import pathlib,sys;p=pathlib.Path(r'{flag}');n=int(p.read_text()) if p.exists() else 0;p.write_text(str(n+1));sys.exit(0 if n>=1 else 1)\""
    p = pl.Pipeline("ci", [
        pl.Step("flaky", flaky, retries=2, retry_delay=0),
        pl.Step("boom", f"{py} -c \"import sys;sys.exit(3)\"", continue_on_error=True),
        pl.Step("cleanup", f"{py} -c \"print('nettoyage')\"", condition="failure"),
        pl.Step("skipme", f"{py} -c \"print('x')\"", condition="branch:release"),
        pl.Step("final", f"{py} -c \"print('fin')\"", condition="always")])
    events = []
    rec = pl.run_pipeline(p, str(tmp_path), runner, branch="main", sleep=lambda s: None, on_event=lambda k, v: events.append(k))
    st = {s["name"]: s for s in rec["steps"]}
    assert st["flaky"]["status"] == "ok" and st["flaky"]["attempts"] == 2
    assert st["boom"]["status"] == "failed" and rec["ok"] is True      # continue_on_error
    assert st["skipme"]["status"] == "skipped" and st["cleanup"]["status"] == "skipped"
    assert "fin" in rec["log"] and "done" in events
    ev = threading.Event()
    ev.set()
    assert pl.run_pipeline(p, str(tmp_path), runner, cancel=ev)["cancelled"]
    failing = pl.Pipeline("f", [pl.Step("a", f"{py} -c \"import sys;sys.exit(1)\""), pl.Step("b", f"{py} -c pass")])
    r2 = pl.run_pipeline(failing, str(tmp_path), runner)
    assert not r2["ok"] and [s["name"] for s in r2["steps"] if s["status"] == "skipped"] == ["b"]


def test_pipeline_validation_and_roundtrip(dc):
    pl = mod("core.pipeline")
    bad = pl.Pipeline("", [pl.Step("a", ""), pl.Step("a", "x", condition="nope", cwd="../x", retries=99)])
    assert len(pl.validate(bad)) >= 5
    ok = pl.Pipeline("p", [pl.Step("s", "echo 1", retries=1)])
    assert pl.Pipeline.from_dict(ok.to_dict()).steps[0].retries == 1
    assert pl.run_pipeline(bad, ".", runner)["ok"] is False


def test_deploy_success_backup_and_auto_restore(dc, tmp_path):
    d = mod("core.deploy")
    proj, dest, bk = tmp_path / "proj", tmp_path / "dest", tmp_path / "bk"
    (proj / "src").mkdir(parents=True)
    (proj / "src" / "app.txt").write_text("v2")
    (proj / "src" / "node_modules").mkdir()
    dest.mkdir()
    (dest / "app.txt").write_text("v1")
    py = sys.executable
    t = d.Target("local", "src", str(dest), health=f"{py} -c pass")
    rec = d.deploy(t, str(proj), bk, runner)
    assert rec["ok"] and (dest / "app.txt").read_text() == "v2" and not (dest / "node_modules").exists() and Path(rec["backup"]).exists()
    # échec de vérification → restauration automatique
    (proj / "src" / "app.txt").write_text("v3-cassé")
    t2 = d.Target("local", "src", str(dest), health=f"{py} -c \"import sys;sys.exit(1)\"")
    rec2 = d.deploy(t2, str(proj), bk, runner)
    assert not rec2["ok"] and rec2["restored"] and (dest / "app.txt").read_text() == "v2"
    assert "restauration" in rec2["log"]


def test_deploy_prod_requires_confirmation_and_guards(dc, tmp_path):
    d = mod("core.deploy")
    (tmp_path / "p").mkdir()
    with pytest.raises(d.DeployError):
        d.deploy(d.Target("x", ".", str(tmp_path / "d"), environment="prod"), str(tmp_path / "p"), tmp_path / "b", runner)
    for bad in (d.Target("x", ".", "/"), d.Target("x", "../..", str(tmp_path / "d")), d.Target("x", ".", str(tmp_path / "d"), ssh="inconnu")):
        with pytest.raises(d.DeployError):
            d.deploy(bad, str(tmp_path / "p"), tmp_path / "b", runner)
    assert d.deploy(d.Target("x", ".", str(tmp_path / "d"), environment="prod"), str(tmp_path / "p"), tmp_path / "b", runner, confirmed=True)["ok"]


def test_deploy_ssh_uses_ssh_and_scp(dc, tmp_path):
    d, R, s = mod("core.deploy"), mod("core.proc").Result, mod("core.ssh")
    calls = []
    (tmp_path / "p").mkdir()
    (tmp_path / "p" / "f").write_text("1")

    def fake(args, **kw):
        calls.append(args[0])
        return R(0, "")
    rec = d.deploy(d.Target("r", ".", "/srv/app", ssh="srv", post=["systemctl restart app"]), str(tmp_path / "p"), tmp_path / "b", fake,
                   {"srv": s.SSHProfile("srv", "h", "u")})
    assert rec["ok"] and "scp" in calls and calls.count("ssh") >= 3 and rec["backup"].startswith("srv:")


def test_environments_and_store(dc, tmp_path):
    e, st = mod("core.environments"), mod("storage.store")
    (tmp_path / "pyproject.toml").write_text("")
    (tmp_path / ".env").write_text("SECRET=1")
    info = e.project_environment(tmp_path)
    assert "Python (pyproject)" in info["markers"] and info["env_files"] == [".env"]
    assert any(t["tool"] == "Python" for t in e.tool_versions(runner))
    s = st.Store(tmp_path / "s")
    s.save("x", [1])
    assert s.load("x", []) == [1] and s.load("none", "d") == "d"
    for i in range(st.HISTORY_MAX + 5):
        s.add_history({"kind": "k", "i": i})
    assert len(s.history()) == st.HISTORY_MAX and s.history()[0]["i"] == st.HISTORY_MAX + 4
    (tmp_path / "s" / "x.json").write_text("{corrompu")
    assert s.load("x", "def") == "def"


def test_widget_end_to_end(dc, repo, tmp_path):
    from PySide6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication([])
    w = mod("ui.widget").DevOpsWidget(mod("storage.store").Store(tmp_path / "s"), runner, confirm=lambda t, x: True)
    w.set_project(repo)
    assert w.git_label.text().startswith("main") and w.git_log.rowCount() == 1 and w.env_tools.rowCount() >= 5
    w.f_name.setText("srv")
    w.f_host.setText("example.org")
    assert w.ssh_save() and w.ssh_table.rowCount() == 1
    w.f_host.setText("-bad")
    assert not w.ssh_save()
    w.pipe_edit.setPlainText('{"name":"t","steps":[{"name":"s","command":"git --version"}]}')
    assert w.pipe_save() and w.pipes_list.count() == 1
    w.pipe_run()
    assert w.hist_table.rowCount() == 1 and "réussi" in w.status.text()
    w.pipe_edit.setPlainText("{pas json")
    assert w._edited_pipeline() is None
    (repo / "x").mkdir()
    w.target_edit.setPlainText('{"name":"loc","source":"x","dest":"%s"}' % (tmp_path / "out"))
    assert w.target_save()
    w.target_deploy()
    assert w.hist_table.rowCount() == 2 and (tmp_path / "out").is_dir()
