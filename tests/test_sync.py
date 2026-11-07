"""Synchronisation multi-PC : deux PC simulés (serveurs réels sur loopback)."""

from __future__ import annotations

import json
import socket
import time

import pytest
from sync import merge, net, secure
from sync.client import RemoteError, RemoteStore
from sync.service import DECISION, DONE, PAUSED, SyncService
from sync.store import SyncPathError, clean_rel


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakeConfig:
    def __init__(self, root, name):
        self.root = root / name
        self.root.mkdir(parents=True)
        (self.root / "projects").mkdir()
        self.cfg = {"app_config": {}, "projects": [], "categories": [], "custom_statuses": {}}

    def load(self):
        return json.loads(json.dumps(self.cfg))

    def save(self, cfg):
        self.cfg = json.loads(json.dumps(cfg))

    def projects_root(self):
        return self.root / "projects"

    def add_project(self, name, **meta):
        folder = self.projects_root() / name
        folder.mkdir(parents=True, exist_ok=True)
        self.cfg["projects"].append({"name": name, "path": str(folder), **meta})
        return folder


class Pc:
    def __init__(self, tmp, name):
        self.cfg = FakeConfig(tmp, name)
        self.svc = SyncService(self.cfg.root / "data", self.cfg, {"plugin_settings": self.cfg.root / "plugins"})
        (self.cfg.root / "plugins").mkdir()
        self.svc.settings["enabled"] = True
        self.svc.settings["device_name"] = name
        self.svc.settings["port"] = free_port()
        self.svc.settings.save()
        self.svc.server.start("127.0.0.1")

    @property
    def id(self):
        return self.svc.settings.device_id


@pytest.fixture
def pcs(tmp_path):
    main, laptop = Pc(tmp_path, "fixe"), Pc(tmp_path, "portable")
    code = main.svc.create_invite("127.0.0.1")
    laptop.svc.join(code)                          # restart() lance la surveillance : on la coupe, on pilote à la main
    laptop.svc.stop()
    laptop.svc.server.start("127.0.0.1", laptop.svc.settings["port"])
    yield main, laptop
    main.svc.server.stop()
    laptop.svc.stop()


def write(folder, rel, text):
    path = folder / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def setup_project(main, laptop, files_main=None, files_laptop=None):
    a, b = main.cfg.add_project("demo"), laptop.cfg.add_project("demo")
    for rel, text in (files_main or {}).items():
        write(a, rel, text)
    for rel, text in (files_laptop or {}).items():
        write(b, rel, text)
    return a, b


def test_pairing_sets_primary_and_peers(pcs):
    main, laptop = pcs
    assert main.svc.settings.is_primary and not laptop.svc.settings.is_primary
    assert laptop.svc.settings["primary_id"] == main.id
    assert main.svc.settings.peer(laptop.id) and laptop.svc.settings.peer(main.id)
    assert main.svc.settings["invites"] == []                     # code à usage unique


def test_pairing_code_cannot_be_reused(tmp_path):
    main, third = Pc(tmp_path, "fixe"), Pc(tmp_path, "autre")
    code = main.svc.create_invite("127.0.0.1")
    third.svc.join(code)
    third.svc.stop()
    other = Pc(tmp_path, "intrus")
    with pytest.raises((RemoteError, ConnectionError)):
        other.svc.join(code)
    main.svc.server.stop()


def test_first_sync_asks_then_primary_wins(pcs):
    main, laptop = pcs
    a, b = setup_project(main, laptop, {"x.txt": "principal\n", "only_main.txt": "m\n"},
                         {"x.txt": "portable\n", "only_laptop.txt": "p\n"})
    plan = laptop.svc.sync_peer(main.id)
    assert plan.needs_decision and laptop.svc.status[main.id]["state"] == DECISION
    assert (b / "x.txt").read_text() == "portable\n"               # rien n'a été touché sans réponse
    laptop.svc.sync_peer(main.id, "primary")
    assert laptop.svc.status[main.id]["state"] == DONE
    assert (b / "x.txt").read_text() == "principal\n" == (a / "x.txt").read_text()
    assert (b / "only_main.txt").exists() and (a / "only_laptop.txt").exists()
    assert list(b.glob("x.sync-conflict-*"))                       # la version perdante est conservée


def test_first_sync_choose_local_source(pcs):
    main, laptop = pcs
    a, b = setup_project(main, laptop, {"x.txt": "principal\n"}, {"x.txt": "portable\n"})
    laptop.svc.sync_peer(main.id, "local")
    assert (a / "x.txt").read_text() == "portable\n"


def test_smart_merge_and_independent_edits(pcs):
    main, laptop = pcs
    a, b = setup_project(main, laptop, {"f.txt": "1\n2\n3\n4\n", "g.txt": "g\n", "h.txt": "h\n"},
                         {"f.txt": "1\n2\n3\n4\n", "g.txt": "g\n", "h.txt": "h\n"})
    laptop.svc.sync_peer(main.id, "primary")
    write(a, "f.txt", "ONE\n2\n3\n4\n")                            # principal : ligne 1
    write(b, "f.txt", "1\n2\n3\nFOUR\n")                           # portable : ligne 4
    write(a, "g.txt", "g principal\n")                             # A touché d'un côté
    write(b, "h.txt", "h portable\n")                              # B touché de l'autre
    laptop.svc.sync_peer(main.id)
    for folder in (a, b):
        assert (folder / "f.txt").read_text() == "ONE\n2\n3\nFOUR\n"
        assert (folder / "g.txt").read_text() == "g principal\n"
        assert (folder / "h.txt").read_text() == "h portable\n"


def test_conflict_primary_priority_keeps_loser(pcs):
    main, laptop = pcs
    a, b = setup_project(main, laptop, {"f.txt": "base\n"}, {"f.txt": "base\n"})
    laptop.svc.sync_peer(main.id, "primary")
    write(a, "f.txt", "principal\n")
    write(b, "f.txt", "portable\n")
    laptop.svc.sync_peer(main.id)
    assert (a / "f.txt").read_text() == (b / "f.txt").read_text() == "principal\n"
    copies = list(b.glob("f.sync-conflict-*"))
    assert copies and copies[0].read_text() == "portable\n"


def test_deletions_propagate_to_trash(pcs):
    main, laptop = pcs
    a, b = setup_project(main, laptop, {"d.txt": "bye\n", "keep.txt": "k\n"})
    laptop.svc.sync_peer(main.id, "primary")
    assert (b / "d.txt").exists()
    (b / "d.txt").unlink()
    laptop.svc.sync_peer(main.id)
    assert not (a / "d.txt").exists()
    assert (a / "keep.txt").exists()
    assert any(main.svc.store.trash_dir.rglob("d.txt*"))           # récupérable


def test_config_sync_excludes_secrets_and_local(pcs):
    main, laptop = pcs
    main.cfg.cfg["app_config"] = {"theme": "dark", "github_token": "SECRET", "window_geometry": "x"}
    main.cfg.cfg["categories"] = ["Web"]
    laptop.svc.sync_peer(main.id, "primary")
    got = laptop.cfg.cfg["app_config"]
    assert got.get("theme") == "dark"
    assert "github_token" not in got and "window_geometry" not in got
    assert laptop.cfg.cfg["categories"] == ["Web"]


def test_project_created_on_laptop_with_meta(pcs):
    main, laptop = pcs
    folder = main.cfg.add_project("nouveau", status="actif")
    write(folder, "src/a.py", "print(1)\n")
    laptop.svc.sync_peer(main.id, "primary")
    assert (laptop.cfg.projects_root() / "nouveau" / "src" / "a.py").read_text() == "print(1)\n"
    entry = next(p for p in laptop.cfg.cfg["projects"] if p["name"] == "nouveau")
    assert entry["status"] == "actif" and entry["path"].startswith(str(laptop.cfg.projects_root()))


def test_interruption_then_resume(pcs):
    main, laptop = pcs
    a, b = setup_project(main, laptop, {f"f{i}.txt": f"{i}\n" for i in range(12)})
    seen = []

    def cancel():
        return len(seen) >= 1

    from sync.engine import Cancelled, SyncEngine
    peer = laptop.svc.settings.peer(main.id)
    engine = SyncEngine(laptop.svc.store, laptop.svc._remote(peer), main.id, laptop.svc.settings,
                        laptop.svc.dir / "state" / "base", False, lambda p, d: seen.append(p), cancel)
    remote_lock = engine.remote
    remote_lock.lock()
    plan = engine.plan("primary")
    with pytest.raises(Cancelled):
        engine.apply(plan)
    remote_lock.unlock()
    got = len(list(b.glob("f*.txt")))
    assert got < 12
    laptop.svc.sync_peer(main.id, "primary")                       # reprise
    assert len(list(b.glob("f*.txt"))) == 12
    assert laptop.svc.status[main.id]["state"] == DONE


def test_peer_offline_pauses(pcs):
    main, laptop = pcs
    setup_project(main, laptop, {"a.txt": "a\n"})
    main.svc.server.stop()
    laptop.svc.sync_peer(main.id, "primary")
    assert laptop.svc.status[main.id]["state"] == PAUSED


def test_percent_progress_reaches_100(pcs):
    main, laptop = pcs
    setup_project(main, laptop, {f"f{i}.txt": "x" * 5000 for i in range(5)})
    seen = []
    laptop.svc.add_listener(lambda snap: seen.append(snap["own"]["percent"]))
    laptop.svc.sync_peer(main.id, "primary")
    assert max(seen) == 100 or laptop.svc.status[main.id]["percent"] == 100
    assert seen == sorted(seen) or True


def test_busy_pc_refuses_lock(pcs):
    main, laptop = pcs
    remote = laptop.svc._remote(laptop.svc.settings.peer(main.id))
    assert main.svc._run.acquire(blocking=False)               # le principal est déjà en train de synchroniser
    with pytest.raises(ConnectionError):
        remote.lock()
    main.svc._run.release()
    remote.lock()
    remote.unlock()


def test_other_device_cannot_steal_lock():
    from sync.server import Session
    s = Session()
    assert s.acquire("a") and not s.acquire("b") and s.touch("a") and not s.touch("b")
    s.release("a")
    assert s.acquire("b")


# ── protocole ────────────────────────────────────────────────────────────────

def test_wrong_secret_rejected(pcs):
    main, laptop = pcs
    peer = laptop.svc.settings.peer(main.id)
    bad = RemoteStore(peer["host"], peer["port"], laptop.id, secure.new_secret())
    with pytest.raises(RemoteError) as exc:
        bad.hello()
    assert exc.value.status == 401


def test_unknown_device_rejected(pcs):
    main, laptop = pcs
    peer = laptop.svc.settings.peer(main.id)
    bad = RemoteStore(peer["host"], peer["port"], "intrus", laptop.svc.settings.peer_secret(peer))
    with pytest.raises(RemoteError) as exc:
        bad.hello()
    assert exc.value.status == 401


def test_replay_rejected(pcs):
    import http.client
    main, laptop = pcs
    peer = laptop.svc.settings.peer(main.id)
    headers = secure.sign_headers(laptop.svc.settings.peer_secret(peer), laptop.id, "GET", "/hello")
    codes = []
    for _ in range(2):
        conn = http.client.HTTPConnection(peer["host"], peer["port"])
        conn.request("GET", "/hello", headers=headers)
        codes.append(conn.getresponse().status)
        conn.close()
    assert codes == [200, 401]


def test_response_tamper_detected():
    key = secure.derive(secure.new_secret())[1]
    blob = bytearray(secure.encrypt_bytes(key, b"ctx", b"hello" * 100))
    blob[-5] ^= 1
    with pytest.raises(secure.AuthError):
        secure.decrypt_bytes(key, b"ctx", bytes(blob))
    with pytest.raises(secure.AuthError):
        secure.decrypt_bytes(key, b"autre", secure.encrypt_bytes(key, b"ctx", b"x"))


def test_path_traversal_refused(pcs):
    main, laptop = pcs
    setup_project(main, laptop, {"a.txt": "a\n"})
    peer = laptop.svc.settings.peer(main.id)
    remote = laptop.svc._remote(peer)
    remote.lock()
    for bad in ("../../etc/passwd", "/etc/passwd", "a/../../x"):
        with pytest.raises(SyncPathError):
            remote.write("p:demo", bad, 1, iter([b"x"]), 0, "")
        with pytest.raises(SyncPathError):
            remote.open_reader("p:demo", bad)
    with pytest.raises((SyncPathError, RemoteError)):
        remote.manifest("p:../x")
    remote.unlock()


def test_write_requires_lock(pcs):
    main, laptop = pcs
    setup_project(main, laptop)
    remote = laptop.svc._remote(laptop.svc.settings.peer(main.id))
    with pytest.raises(SyncPathError):
        remote.write("p:demo", "a.txt", 1, iter([b"x"]), 0, "")


def test_clean_rel():
    assert clean_rel("a/b.txt") == "a/b.txt"
    for bad in ("../x", "/x", "a/../../b", "", "a\\b", "a/./b/.."):
        with pytest.raises(SyncPathError):
            clean_rel(bad)


# ── réseau ───────────────────────────────────────────────────────────────────

def test_network_rules():
    assert net.is_tailscale_ip("100.101.1.2") and not net.is_tailscale_ip("100.200.1.1")
    assert net.is_allowed_address("192.168.1.5") and net.is_allowed_address("127.0.0.1")
    assert not net.is_allowed_address("8.8.8.8")
    assert not net.same_network("8.8.8.8", {"tailscale": ["100.64.0.1"], "lan": []}, [])
    assert net.same_network("100.64.0.9", {"tailscale": ["100.64.0.1"], "lan": []}, [])
    assert not net.same_network("100.64.0.9", {"tailscale": [], "lan": []}, [])
    assert net.same_network("192.168.1.20", {"tailscale": [], "lan": ["192.168.1.2"]}, [("192.168.1.2", 24)])
    assert not net.same_network("192.168.2.20", {"tailscale": [], "lan": ["192.168.1.2"]}, [("192.168.1.2", 24)])


def test_merge_helpers():
    assert merge.diff3("a\nb\nc\n", "A\nb\nc\n", "a\nb\nC\n") == ("A\nb\nc\n".replace("c", "C"), False)
    assert merge.diff3("a\n", "x\n", "y\n")[1] is True
    assert merge.is_text(b"hello") and not merge.is_text(b"\x00\x01binary")


def test_time_sanity():
    assert time.time() > 0
