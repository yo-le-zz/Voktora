"""Synchronisation multi-PC : deux PC simulés (serveurs réels sur loopback)."""

from __future__ import annotations

import json
import socket
import time

import pytest
from sync import merge, net, secure
from sync.client import RemoteError, RemoteStore
from sync.service import DECISION, DONE, PAUSED, SyncService
from sync.store import PART_SUFFIX, SyncPathError, clean_rel


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
        return bool(seen) and max(seen) >= 25               # on coupe en pleine application

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
    assert laptop.svc.status[main.id]["percent"] == 100
    assert max(seen) >= 20 and 0 < len({p for p in seen}) <= 101


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
    with pytest.raises(ConnectionError):                       # LockLost : appelez /lock d'abord
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


# ── bavardage, ports automatiques, réseau instable ───────────────────────────

def test_sync_is_talkative(pcs):
    main, laptop = pcs
    setup_project(main, laptop, {"a.txt": "a\n", "b.txt": "b\n"})
    laptop.svc.sync_peer(main.id, "primary")
    text = "\n".join(laptop.svc.logs)
    for expected in ("Début de la synchronisation", "réservé", "à comparer", "Comparaison de projet « demo »",
                     "Application : 2 action(s)", "Terminé : demo", "Terminé en"):
        assert expected in text, expected
    assert "Réception" not in text                      # le détail par fichier n'est pas au niveau « normal »
    assert (laptop.svc.dir / "sync.log").exists()


def test_detailed_level_logs_each_file(pcs):
    main, laptop = pcs
    laptop.svc.settings["log_level"] = "detailed"
    setup_project(main, laptop, {"a.txt": "a\n"})
    laptop.svc.sync_peer(main.id, "primary")
    assert "Réception projet" not in "\n".join(laptop.svc.logs) and "Réception demo/a.txt" in "\n".join(laptop.svc.logs)


def test_log_can_be_disabled_and_cleared(pcs):
    main, laptop = pcs
    setup_project(main, laptop, {"a.txt": "a\n"})
    laptop.svc.sync_peer(main.id, "primary")
    assert laptop.svc.logs and (laptop.svc.dir / "sync.log").exists()
    laptop.svc.clear_log()
    assert not laptop.svc.logs and not (laptop.svc.dir / "sync.log").exists()
    laptop.svc.settings["log_enabled"] = False
    laptop.svc.sync_peer(main.id)
    assert not laptop.svc.logs and not (laptop.svc.dir / "sync.log").exists()


def test_quiet_level_keeps_essentials_only(pcs):
    main, laptop = pcs
    laptop.svc.settings["log_level"] = "quiet"
    setup_project(main, laptop, {"a.txt": "a\n"})
    laptop.svc.clear_log()                               # le jumelage de la fixture a pu journaliser en « normal »
    laptop.svc.sync_peer(main.id, "primary")
    text = "\n".join(laptop.svc.logs)
    assert "Début de la synchronisation" in text and "Terminé en" in text and "Comparaison de" not in text


def test_ui_emissions_are_throttled(pcs):
    main, laptop = pcs
    laptop.svc.settings["performance"] = "eco"
    seen = []
    laptop.svc.add_listener(lambda snap: seen.append(time.monotonic()))
    for i in range(200):
        laptop.svc.log(f"ligne {i}", important=True)
    assert len(seen) < 20                                # 200 lignes, très peu de rafraîchissements d'interface
    time.sleep(1.0)
    assert laptop.svc.log_total >= 200


def test_phase_details_in_status(pcs):
    main, laptop = pcs
    setup_project(main, laptop, {"a.txt": "a\n"})
    details = []
    real_set = laptop.svc._set
    laptop.svc._set = lambda pid, **f: (details.append(f.get("detail", "")), real_set(pid, **f))[1]
    laptop.svc.sync_peer(main.id, "primary")
    joined = " | ".join(details)
    assert "Connexion à" in joined and "Comparaison de" in joined and "Réception" in joined


def test_port_busy_picks_another_and_peer_finds_it(tmp_path):
    blocker = socket.socket()
    blocker.bind(("0.0.0.0", 0))
    busy = blocker.getsockname()[1]
    a = Pc(tmp_path, "un")
    a.svc.server.stop()
    a.svc.settings["port"] = busy
    a.svc.settings.save()
    a.svc.start()
    try:
        assert a.svc.server.port != busy and a.svc.settings["port"] == a.svc.server.port
    finally:
        a.svc.stop()
        blocker.close()


def test_peer_changed_port_is_rediscovered(pcs):
    main, laptop = pcs
    from sync.settings import DEFAULT_PORT
    main.svc.server.stop()
    main.svc.server.start("127.0.0.1", DEFAULT_PORT + 3)
    laptop.svc._stop.clear()                                   # (la surveillance est coupée dans ces tests)
    peer = laptop.svc.settings.peer(main.id)
    info = laptop.svc._hello(peer, laptop.svc._remote(peer))
    assert info["id"] == main.id and peer["port"] == DEFAULT_PORT + 3


def test_transient_failure_is_retried(pcs, monkeypatch):
    main, laptop = pcs
    setup_project(main, laptop, {"a.txt": "a\n"})
    remote = laptop.svc._remote(laptop.svc.settings.peer(main.id))
    calls = {"n": 0}
    real = remote._manifest_once

    def flaky(space, progress):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("coupure")
        return real(space, progress)
    monkeypatch.setattr(remote, "_manifest_once", flaky)
    monkeypatch.setattr("sync.client.RETRY_DELAYS", (0.0, 0.0))
    remote.lock()
    messages = []
    got = remote.manifest("p:demo", on_retry=lambda a, t, e: messages.append(str(e)))
    remote.unlock()
    assert "a.txt" in got and calls["n"] == 2 and messages


def test_lock_expiry_is_recovered(pcs):
    main, laptop = pcs
    setup_project(main, laptop, {"a.txt": "a\n"})
    remote = laptop.svc._remote(laptop.svc.settings.peer(main.id))
    remote.lock()
    main.svc.server.session.release(laptop.id)             # le verrou a expiré côté principal
    assert "a.txt" in remote.manifest("p:demo")              # relock automatique puis nouvel essai
    remote.unlock()


def test_diagnose_reports_each_step(pcs):
    main, laptop = pcs
    steps = laptop.svc.diagnose(main.id)
    assert all(ok for ok, _ in steps), steps
    assert any("Authentification OK" in t for _, t in steps)
    main.svc.server.stop()
    bad = laptop.svc.diagnose(main.id)
    assert not bad[-1][0] and "Port" in bad[-1][1]


def test_manifest_streams_progress(pcs):
    main, laptop = pcs
    a, _ = setup_project(main, laptop, {f"d{i}/f{i}.txt": "x" for i in range(30)})
    remote = laptop.svc._remote(laptop.svc.settings.peer(main.id))
    remote.lock()
    seen = []
    import sync.store as store_mod
    real = main.svc.store._scan

    def slow(root, is_project, cancel, progress=None):
        import time as t
        t0 = store_mod.time.monotonic
        store_mod.time.monotonic = lambda: t0() + t.time() * 1000      # chaque tick passe le seuil de 0,4 s
        try:
            return real(root, is_project, cancel, progress)
        finally:
            store_mod.time.monotonic = t0
    main.svc.store._scan = slow
    got = remote.manifest("p:demo", progress=lambda n, w: seen.append((n, w)))
    remote.unlock()
    assert len(got) == 30 and seen


def test_unknown_space_is_clean_error(pcs):
    main, laptop = pcs
    remote = laptop.svc._remote(laptop.svc.settings.peer(main.id))
    remote.lock()
    with pytest.raises((SyncPathError, RemoteError)):
        remote.manifest("zzz")
    remote.unlock()


def test_mass_delete_is_never_propagated(pcs):
    main, laptop = pcs
    a, b = setup_project(main, laptop, {f"f{i}.txt": "x\n" for i in range(40)})
    laptop.svc.sync_peer(main.id, "primary")
    for f in b.glob("f*.txt"):                              # le portable « perd » tout (disque démonté, dossier vidé…)
        f.unlink()
    plan = laptop.svc.sync_peer(main.id)
    assert plan.warnings and "suppressions ignorées" in plan.warnings[0]
    assert len(list(a.glob("f*.txt"))) == 40                # le principal est intact
    again = laptop.svc.sync_peer(main.id)                    # l'avertissement se répète tant que ce n'est pas tranché
    assert again.warnings and len(list(a.glob("f*.txt"))) == 40


def test_project_known_only_on_disk_is_not_wiped(pcs):
    main, laptop = pcs
    a, _ = setup_project(main, laptop, {"k.txt": "k\n"})
    laptop.cfg.cfg["projects"].clear()                       # projet reçu mais pas encore déclaré ici
    laptop.cfg.projects_root().joinpath("demo").mkdir(exist_ok=True)
    laptop.svc.sync_peer(main.id, "primary")
    laptop.svc.sync_peer(main.id)
    assert (a / "k.txt").exists()


# ── reprise là où la synchronisation s'était arrêtée ─────────────────────────

def test_resume_continues_where_it_stopped(pcs):
    main, laptop = pcs
    a, b = setup_project(main, laptop, {f"f{i}.txt": "x" * 3000 + f"{i}\n" for i in range(30)})
    from sync.engine import Cancelled, SyncEngine
    peer = laptop.svc.settings.peer(main.id)
    seen = []
    engine = SyncEngine(laptop.svc.store, laptop.svc._remote(peer), main.id, laptop.svc.settings,
                        laptop.svc.dir / "state" / "base", False, lambda p, d: seen.append(p),
                        lambda: bool(seen) and max(seen) >= 60)
    engine.on_checkpoint = lambda dw, tw, n: laptop.svc._save_resume(main.id, status="running", done_weight=dw,
                                                                      total_weight=tw, done=n)
    engine.remote.lock()
    plan = engine.plan("primary")
    with pytest.raises(Cancelled):
        engine.apply(plan)
    engine.remote.unlock()
    done_before = len(list(b.glob("f*.txt")))
    info = laptop.svc.resume_info(main.id)
    assert 0 < done_before < 30 and info["status"] == "running" and info["done"] >= 1
    # reprise : seul le reste est refait, le pourcentage repart d'où il était, le choix « primary » est retenu
    laptop.svc._save_resume(main.id, status="interrupted", choice="primary")
    percents = []
    real_set = laptop.svc._set
    laptop.svc._set = lambda pid, **f: (percents.append(f.get("percent")), real_set(pid, **f))[1]
    plan2 = laptop.svc.sync_peer(main.id)            # aucun choix passé : celui d'avant est réutilisé
    assert plan2 is not None and not plan2.needs_decision
    assert len(list(b.glob("f*.txt"))) == 30
    assert sum(1 for x in plan2.actions if x.kind == "pull") == 30 - done_before
    assert any("Reprise de la synchronisation interrompue" in line for line in laptop.svc.logs)
    first_apply_pct = min(p for p in percents if p and p > 20)
    assert first_apply_pct >= 20 + int(80 * info["done_weight"] / info["total_weight"]) - 5
    assert laptop.svc.resume_info(main.id) == {}      # terminé : plus rien à reprendre


def test_pause_message_says_where_it_resumes(pcs):
    main, laptop = pcs
    setup_project(main, laptop, {"a.txt": "a\n"})
    main.svc.server.stop()
    laptop.svc.sync_peer(main.id, "primary")
    st = laptop.svc.status[main.id]
    assert st["state"] == PAUSED and "reprendra" in st["detail"]
    assert laptop.svc.resume_info(main.id)["status"] == "interrupted"


def test_decision_choice_survives_interruption(pcs):
    main, laptop = pcs
    setup_project(main, laptop, {"x.txt": "p\n"}, {"x.txt": "q\n"})
    plan = laptop.svc.sync_peer(main.id)
    assert plan.needs_decision
    laptop.svc._save_resume(main.id, choice="local")            # l'utilisateur avait répondu « ce PC »…
    laptop.svc.sync_peer(main.id)                               # …puis coupure ; au retour on ne redemande pas
    assert laptop.svc.status[main.id]["state"] == DONE


def test_stale_partial_files_are_purged(pcs):
    main, laptop = pcs
    a, b = setup_project(main, laptop, {"a.txt": "a\n"})
    part = b / f"gros.bin{PART_SUFFIX}"
    part.write_text("moitié de fichier")
    import os
    os.utime(part, (time.time() - 7200, time.time() - 7200))
    laptop.svc.sync_peer(main.id, "primary")
    assert not part.exists()


def test_projects_appear_progressively_and_cfg_first(pcs):
    main, laptop = pcs
    for i in range(3):
        write(main.cfg.add_project(f"p{i}"), "f.txt", "x\n")
    order = []
    real = laptop.svc._space_done
    laptop.svc._space_done = lambda pid, sp, k, n: (order.append((sp, len(laptop.cfg.cfg["projects"]))), real(pid, sp, k, n))[1]
    laptop.svc.sync_peer(main.id, "primary")
    assert order[0][0] == "cfg" or order[0][1] == 3               # la liste des projets arrive avant leurs fichiers
    assert laptop.svc.status[main.id].get("changed_at")


def test_performance_profiles():
    import tempfile

    from sync.settings import SyncSettings
    s = SyncSettings(tempfile.mkdtemp())
    s["performance"] = "eco"
    assert s.performance_profile()["scans"] == 1 and s.performance_profile()["nice"] > 0
    s["performance"] = "fast"
    assert s.performance_profile()["scans"] == 4
    s["performance"] = "auto"
    assert s.performance_profile()["mode"] in ("eco", "normal", "fast")
