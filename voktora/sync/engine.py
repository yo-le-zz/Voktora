"""
Voktora — sync.engine
Plan puis application de la synchronisation entre deux magasins (le local et celui d'un pair).

Fusion à trois voies par élément (fichier ou réglage), avec comme « base » l'état au dernier échange réussi :
  • modifié d'un seul côté            → on copie de ce côté vers l'autre (suppressions comprises) ;
  • modifié des DEUX côtés            → fusion de texte si les changements ne se chevauchent pas (les deux
                                        modifications sont appliquées) ; sinon CONFLIT : le PC principal gagne,
                                        la version perdante est conservée à côté (`….sync-conflict-…`) ;
  • jamais synchronisé et différent   → selon `first_sync` : demander à l'utilisateur de quel côté partir,
                                        ou principal / local / distant gagnent.
`.git/` est un bloc : en cas de conflit à l'intérieur, tout le bloc suit le gagnant (pas de fusion de fichiers
internes). L'état est enregistré au fur et à mesure : une coupure (PC éteint, réseau perdu) n'annule rien et la
synchronisation reprend où elle s'était arrêtée.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import merge
from .settings import SyncSettings
from .store import CFG, Entry, LocalStore, SyncPathError

BLOB_MAX = 256 * 1024
MIN_WEIGHT = 4096
PARALLEL_SCANS = 4
SYNC_CONFLICT = ".sync-conflict-"

PULL, PUSH, DEL_LOCAL, DEL_REMOTE, MERGE = "pull", "push", "delete_local", "delete_remote", "merge"
FIRST_SYNC_CHOICES = ("ask", "primary", "local", "remote")


class SyncError(Exception):
    pass


class Cancelled(SyncError):
    """Arrêt demandé (ou pair éteint)."""


class PeerGone(SyncError):
    """Le pair ne répond plus (éteint, réseau perdu) : la synchronisation reprendra plus tard."""


@dataclass
class Action:
    space: str
    rel: str
    kind: str
    size: int = 0
    sha: str = ""                 # empreinte visée après l'action (pull/push)
    mode: int = 0
    note: str = ""                # ex. « conflit : le principal gagne »
    conflict_copy: bool = False   # sauvegarder d'abord la version perdante à côté (locale)
    loser_remote: bool = False

    @property
    def weight(self) -> int:
        return max(self.size, MIN_WEIGHT)


@dataclass
class Decision:
    space: str
    count: int
    examples: list[str] = field(default_factory=list)


@dataclass
class Plan:
    peer_id: str
    actions: list[Action] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    unchanged: int = 0
    base_updates: dict[str, dict[str, str | None]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    base_blobs: list[tuple[str, str]] = field(default_factory=list)   # fichiers identiques dont on garde le texte

    @property
    def total_bytes(self) -> int:
        return sum(a.size for a in self.actions)

    @property
    def needs_decision(self) -> bool:
        return bool(self.decisions)

    def count(self, kind: str) -> int:
        return sum(1 for a in self.actions if a.kind == kind)

    def summary(self) -> str:
        if not self.actions and not self.decisions:
            return "Tout est à jour."
        parts = [f"{self.count(k)} {label}" for k, label in
                 ((PULL, "reçu(s)"), (PUSH, "envoyé(s)"), (MERGE, "fusionné(s)"),
                  (DEL_LOCAL, "supprimé(s) ici"), (DEL_REMOTE, "supprimé(s) là-bas")) if self.count(k)]
        conflicts = sum(1 for a in self.actions if a.conflict_copy)
        if conflicts:
            parts.append(f"{conflicts} conflit(s) (le principal gagne)")
        if self.decisions:
            parts.append(f"{sum(d.count for d in self.decisions)} divergence(s) à trancher")
        return ", ".join(parts)


def _safe(space: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", space)


class BaseState:
    """Dernier état synchronisé avec UN pair (+ copies du texte pour la fusion 3 voies)."""

    def __init__(self, root: Path, peer_id: str):
        self.root = Path(root) / _safe(peer_id)
        self._data: dict[str, dict[str, str]] = {}
        self._dirty: set[str] = set()

    def _file(self, space: str) -> Path:
        return self.root / f"{_safe(space)}.json"

    def get(self, space: str) -> dict[str, str]:
        if space not in self._data:
            try:
                self._data[space] = json.loads(self._file(space).read_text(encoding="utf-8")).get("files", {})
            except (OSError, json.JSONDecodeError, AttributeError):
                self._data[space] = {}
        return self._data[space]

    def set(self, space: str, rel: str, sha: str | None) -> None:
        files = self.get(space)
        if sha is None:
            files.pop(rel, None)
        else:
            files[rel] = sha
        self._dirty.add(space)

    def flush(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        for space in list(self._dirty):
            tmp = self._file(space).with_suffix(".tmp")
            tmp.write_text(json.dumps({"files": self._data[space]}, separators=(",", ":")), encoding="utf-8")
            os.replace(tmp, self._file(space))
        self._dirty.clear()

    def blob_path(self, sha: str) -> Path:
        return self.root / "blobs" / sha[:2] / sha

    def save_blob(self, data: bytes) -> None:
        sha = hashlib.sha256(data).hexdigest()
        if len(data) <= BLOB_MAX and merge.is_text(data):
            path = self.blob_path(sha)
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)

    def load_blob(self, sha: str) -> bytes | None:
        try:
            return self.blob_path(sha).read_bytes()
        except OSError:
            return None


def _label(space: str) -> str:
    if space == CFG:
        return "les réglages"
    if space.startswith("p:"):
        return f"projet « {space[2:]} »"
    return "réglages des plugins" if space == "x:plugin_settings" else space


class SyncEngine:
    def __init__(self, local: LocalStore, remote, peer_id: str, settings: SyncSettings, state_root: Path,
                 primary_is_local: bool, on_progress: Callable[[int, str], None] | None = None,
                 cancel: Callable[[], bool] | None = None, local_name: str = "ce PC",
                 on_step: Callable[[str], None] | None = None, peer_name: str = "l'autre PC"):
        self.local, self.remote, self.peer_id, self.settings = local, remote, peer_id, settings
        self.primary_is_local = primary_is_local
        self.base = BaseState(state_root, peer_id)
        self.on_progress, self.cancel, self.local_name = on_progress, cancel, local_name
        self.on_step, self.peer_name = on_step, peer_name
        self.errors: list[str] = []
        self._last_beat = time.monotonic()
        self._pct = 0
        self._absent_local: set[str] = set()

    # ── messages ─────────────────────────────────────────────────────────────

    def _say(self, text: str, percent: int | None = None, log: bool = True) -> None:
        """Annonce une étape : texte lisible (journal + interface) et pourcentage global."""
        if log and self.on_step:
            self.on_step(text)
        if self.on_progress and percent is not None:
            self._pct = max(self._pct, percent)          # jamais de recul (analyses parallèles)
            self.on_progress(self._pct, text)

    def _beat(self) -> None:
        """Garde le verrou de l'autre PC vivant pendant les longues analyses locales."""
        if time.monotonic() - self._last_beat > 20 and hasattr(self.remote, "keepalive"):
            self._last_beat = time.monotonic()
            with contextlib.suppress(ConnectionError, OSError):
                self.remote.keepalive()

    # ── helpers ──────────────────────────────────────────────────────────────

    def _check(self) -> None:
        if self.cancel and self.cancel():
            raise Cancelled("Synchronisation arrêtée.")

    def _spaces(self) -> list[str]:
        local = self.local.spaces()
        spaces = [s for s in local]
        if any(s.startswith("p:") for s in local) or self.settings.category("project_files"):
            for s in self._remote(self.remote.spaces):
                if s.startswith("p:") and s not in spaces and self.settings.project_selected(s[2:]) \
                        and self.settings.category("project_files"):
                    spaces.append(s)
        projects = sorted(s for s in spaces if s.startswith("p:"))
        return projects + [s for s in spaces if s == "x:plugin_settings"] + ([CFG] if CFG in spaces else [])

    def _remote(self, fn, *args):
        try:
            return fn(*args)
        except (ConnectionError, TimeoutError, OSError) as exc:
            if isinstance(exc, FileNotFoundError):
                raise
            raise PeerGone(f"Le pair ne répond plus ({exc}).") from exc

    def _local_manifest(self, space: str) -> dict[str, Entry]:
        def progress(count: int, where: str) -> None:
            self._beat()
            self._say(f"Analyse de {_label(space)} sur ce PC : {count} fichiers lus ({where})",
                      int(20 * (self._index + 0.2) / self._count), log=False)
        try:
            return self.local.manifest(space, self.cancel, progress)
        except SyncPathError:
            self._absent_local.add(space)              # projet absent d'ici : sera créé à la réception
            return {}
        except InterruptedError as exc:
            raise Cancelled("Synchronisation arrêtée.") from exc

    # ── planification ────────────────────────────────────────────────────────

    def plan(self, first_sync: str = "ask") -> Plan:
        if first_sync not in FIRST_SYNC_CHOICES:
            raise ValueError(first_sync)
        plan = Plan(self.peer_id)
        self._say("Recherche des projets à comparer…", 1)
        spaces = self._spaces()
        names = [_label(sp) for sp in spaces]
        self._say(f"{len(spaces)} élément(s) à comparer : {', '.join(names[:6])}{'…' if len(names) > 6 else ''}", 2)
        self._index, self._count = 0, max(1, len(spaces))
        # Avec beaucoup de projets (100+), on analyse plusieurs espaces à la fois — ce PC et l'autre en parallèle —
        # pendant que la comparaison avance dans l'ordre. Les résultats sont gardés au fil de l'eau (mémoire bornée).
        from concurrent.futures import ThreadPoolExecutor
        self._pool = ThreadPoolExecutor(max_workers=PARALLEL_SCANS, thread_name_prefix="voktora-scan")
        self._futures: dict[str, tuple] = {}
        try:
            window = PARALLEL_SCANS * 2
            for index, space in enumerate(spaces):
                self._check()
                for ahead in spaces[index:index + window]:
                    self._prefetch(ahead)
                self._index = index
                self._say(f"Comparaison de {_label(space)} ({index + 1}/{len(spaces)})", int(20 * index / self._count))
                self._plan_space(plan, space, first_sync)
        finally:
            self._pool.shutdown(wait=False, cancel_futures=True)
            with contextlib.suppress(Exception):
                self.local.flush_cache()
        self._say(f"Analyse terminée : {plan.summary()}", 20)
        return plan

    def _prefetch(self, space: str) -> None:
        if space in self._futures:
            return
        self._futures[space] = (self._pool.submit(self._local_manifest, space),
                                self._pool.submit(self._remote_manifest, space))

    def _winner_is_local(self, first_sync: str) -> bool:
        if first_sync == "local":
            return True
        if first_sync == "remote":
            return False
        return self.primary_is_local

    def _plan_space(self, plan: Plan, space: str, first_sync: str) -> None:
        self._prefetch(space)
        fut_local, fut_remote = self._futures.pop(space)
        L = fut_local.result()
        self._say(f"{_label(space)} : {len(L)} élément(s) sur ce PC", log=True)
        R = fut_remote.result()
        self._say(f"{_label(space)} : {len(R)} élément(s) chez {self.peer_name}")
        self._compare(plan, space, first_sync, L, R)

    def _remote_manifest(self, space: str) -> dict[str, Entry]:
        def remote_progress(count: int, where: str) -> None:
            self._say(f"{self.peer_name} analyse {_label(space)} : {count} fichiers lus ({where})",
                      int(20 * (self._index + 0.6) / self._count), log=False)

        def retry(attempt: int, total: int, error) -> None:
            self._say(f"Connexion instable ({error}) — nouvelle tentative {attempt}/{total}…")
        return self._remote(self.remote.manifest, space, remote_progress, retry)

    def _compare(self, plan: Plan, space: str, first_sync: str, L: dict[str, Entry], R: dict[str, Entry]) -> None:
        B = {} if space in self._absent_local else self.base.get(space)   # absent ici ≠ « supprimé par l'utilisateur »
        is_cfg, is_project = space == CFG, space.startswith("p:")
        first_action = len(plan.actions)
        pending = Decision(space, 0)
        git_conflict = False
        undecided: list[Action] = []
        for rel in sorted(set(L) | set(R) | set(B)):
            le, r, b = L.get(rel), R.get(rel), B.get(rel)
            ls, rs = le.sha if le else None, r.sha if r else None
            in_git = is_project and (rel.startswith(".git/"))
            if ls == rs:
                if ls is not None and b != ls:
                    plan.base_updates.setdefault(space, {})[rel] = ls
                    if not is_cfg and le is not None and le.size <= BLOB_MAX:
                        plan.base_blobs.append((space, rel))
                elif ls is None and b is not None:
                    plan.base_updates.setdefault(space, {})[rel] = None
                plan.unchanged += 1
                continue
            if b is None and ls is not None and rs is not None:                       # divergent, jamais synchronisé
                if first_sync == "ask":
                    pending.count += 1
                    if len(pending.examples) < 5:
                        pending.examples.append(rel)
                    continue
                act = self._conflict(space, rel, le, r, self._winner_is_local(first_sync), is_cfg, in_git)
                undecided.append(act)
                git_conflict |= in_git
                continue
            if ls == b and rs != b:                                                    # seul le distant a changé
                plan.actions.append(Action(space, rel, DEL_LOCAL) if r is None else
                                    Action(space, rel, PULL, r.size, r.sha, r.mode))
                if r is None and not self.settings["propagate_deletes"]:
                    plan.actions.pop()
                continue
            if rs == b and ls != b:                                                    # seul le local a changé
                plan.actions.append(Action(space, rel, DEL_REMOTE) if le is None else
                                    Action(space, rel, PUSH, le.size, le.sha, le.mode))
                if le is None and not self.settings["propagate_deletes"]:
                    plan.actions.pop()
                continue
            # modifié des deux côtés par rapport à la base
            if not is_cfg and not in_git and ls and rs and self._try_merge(plan, space, rel, le, r, b):
                continue
            act = self._conflict(space, rel, le, r, self.primary_is_local, is_cfg, in_git)
            undecided.append(act)
            git_conflict |= in_git
        if pending.count:
            plan.decisions.append(pending)
        if git_conflict:
            self._unify_git(plan, space, L, R, undecided)
        else:
            plan.actions.extend(undecided)
        self._guard_mass_delete(plan, space, first_action, len(B))

    def _guard_mass_delete(self, plan: Plan, space: str, first: int, base_size: int) -> None:
        """Garde-fou : une suppression massive (dossier vidé / disque démonté / projet pas encore présent) n'est
        JAMAIS propagée automatiquement. Elle est ignorée avec un avertissement."""
        mine = plan.actions[first:]
        dels = [a for a in mine if a.kind in (DEL_LOCAL, DEL_REMOTE) and not a.note]
        if len(dels) > 20 and len(dels) > base_size * 0.5:
            plan.actions[first:] = [a for a in mine if a not in dels]
            plan.warnings.append(f"{_label(space)} : {len(dels)} suppressions ignorées (trop massif pour être sûr). "
                                 "Supprimez les fichiers voulus à la main si c'est voulu.")

    def _try_merge(self, plan: Plan, space: str, rel: str, le: Entry, r: Entry, b: str | None) -> bool:
        if not b or le.size > 256 * 1024 or r.size > 256 * 1024:
            return False
        base = self.base.load_blob(b)
        if base is None:
            return False
        try:
            _, ldata = self.local.open_reader(space, rel)
            local_bytes = b"".join(ldata)
            _, rdata = self._remote(self.remote.open_reader, space, rel)
            remote_bytes = b"".join(rdata)
        except (OSError, SyncPathError):
            return False
        if not (merge.is_text(local_bytes) and merge.is_text(remote_bytes) and merge.is_text(base)):
            return False
        merged, conflict = merge.diff3(base.decode(), local_bytes.decode(), remote_bytes.decode())
        if conflict:
            return False
        data = merged.encode()
        plan.actions.append(Action(space, rel, MERGE, len(data), hashlib.sha256(data).hexdigest(), le.mode,
                                   note="les deux modifications sont appliquées"))
        return True

    def _conflict(self, space: str, rel: str, le: Entry | None, r: Entry | None, local_wins: bool,
                  is_cfg: bool, in_git: bool) -> Action:
        keep_copy = not is_cfg and not in_git
        winner, loser = (le, r) if local_wins else (r, le)
        who = "ce PC" if local_wins else "l'autre PC"
        if winner is None:                    # le gagnant a supprimé
            act = Action(space, rel, DEL_REMOTE if local_wins else DEL_LOCAL, note=f"conflit : {who} (principal) a supprimé")
        else:
            kind = PUSH if local_wins else PULL
            act = Action(space, rel, kind, winner.size, winner.sha, winner.mode, note=f"conflit : {who} gagne")
        act.conflict_copy = keep_copy and loser is not None
        act.loser_remote = local_wins
        return act

    def _unify_git(self, plan: Plan, space: str, L, R, acts: list[Action]) -> None:
        """Un conflit dans .git/ : tout le bloc suit le PC qui gagne (principal)."""
        local_wins = self.primary_is_local
        non_git = [a for a in acts if not a.rel.startswith(".git/")]
        plan.actions.extend(non_git)
        rels = {r for r in set(L) | set(R) if r.startswith(".git/")}
        for rel in sorted(rels):
            le, r = L.get(rel), R.get(rel)
            ls, rs = (le.sha if le else None), (r.sha if r else None)
            if ls == rs:
                continue
            win = (le if local_wins else r)
            if win is None:
                plan.actions.append(Action(space, rel, DEL_REMOTE if local_wins else DEL_LOCAL, note="bloc .git : le principal gagne"))
            else:
                plan.actions.append(Action(space, rel, PUSH if local_wins else PULL, win.size, win.sha, win.mode,
                                           note="bloc .git : le principal gagne"))
        plan.warnings.append(f"{space} : l'historique git diffère sur les deux PC — celui du principal est conservé.")

    # ── application ──────────────────────────────────────────────────────────

    def apply(self, plan: Plan) -> dict:
        """Exécute le plan. Retourne {"done", "errors"}. Lève Cancelled / PeerGone après avoir enregistré l'état."""
        total = max(1, sum(a.weight for a in plan.actions))
        done_weight, done = 0, 0
        self._say(f"Application : {len(plan.actions)} action(s) à faire" if plan.actions else "Rien à transférer.", 20)
        touched: set[str] = set()
        for space, updates in plan.base_updates.items():
            for rel, sha in updates.items():
                self.base.set(space, rel, sha)
        for space, rel in plan.base_blobs:
            with contextlib.suppress(OSError, SyncPathError):
                _, chunks = self.local.open_reader(space, rel)
                self.base.save_blob(b"".join(chunks))
        try:
            for index, action in enumerate(plan.actions):
                self._check()
                verb = {PULL: "Réception", PUSH: "Envoi", MERGE: "Fusion", DEL_LOCAL: "Suppression ici",
                        DEL_REMOTE: "Suppression là-bas"}.get(action.kind, action.kind)
                where = f"réglage {action.rel}" if action.space == CFG else f"{action.space[2:] or action.space}/{action.rel}"
                self._say(f"{verb} {where} ({index + 1}/{len(plan.actions)})",
                          20 + int(done_weight * 80 / total), log=index < 200 or index % 20 == 0)
                try:
                    self._do_retry(action)
                    touched.add(action.space)
                    done += 1
                except (SyncPathError, FileNotFoundError, OSError) as exc:
                    if isinstance(exc, ConnectionError | TimeoutError):
                        raise
                    self.errors.append(f"{action.space}:{action.rel} — {exc}")
                done_weight += action.weight
                if index % 25 == 24:
                    self.base.flush()
            for space in touched:
                self.local.commit(space)
                self._remote(self.remote.commit, space)
            if self.on_progress:
                self.on_progress(100, "terminé")
        except (ConnectionError, TimeoutError) as exc:
            raise PeerGone(f"Le pair ne répond plus ({exc}).") from exc
        finally:
            self.base.flush()
            for space in touched:
                with contextlib.suppress(Exception):
                    self.local.commit(space)
        return {"done": done, "errors": list(self.errors)}

    def _do_retry(self, action: Action) -> None:
        """Rejoue une action après une coupure réseau brève ; au-delà, le pair est considéré absent (reprise plus tard)."""
        from .client import RETRY_DELAYS, LockLost
        last: Exception | None = None
        for attempt, delay in enumerate((0.0, *RETRY_DELAYS)):
            if delay:
                self._say(f"Connexion instable, nouvelle tentative {attempt}/{len(RETRY_DELAYS)} "
                          f"({action.rel})…")
                time.sleep(delay)
                self._check()
            try:
                if last is not None and hasattr(self.remote, "relock"):
                    with contextlib.suppress(ConnectionError):
                        self.remote.relock()
                return self._do(action)
            except (ConnectionError, TimeoutError, LockLost) as exc:
                last = exc
        raise PeerGone(f"Le pair ne répond plus ({last}).") from last

    def _do(self, a: Action) -> None:
        local, remote = self.local, self.remote
        if a.conflict_copy:
            self._save_conflict_copy(a)
        if a.kind == PULL:
            size, chunks = self._remote(remote.open_reader, a.space, a.rel)
            data = self._tee(chunks, a)
            local.write(a.space, a.rel, data, a.mode, expected_sha=a.sha)
            self.base.set(a.space, a.rel, a.sha)
        elif a.kind == PUSH:
            size, chunks = local.open_reader(a.space, a.rel)
            self._remote(remote.write, a.space, a.rel, size, self._tee(chunks, a), a.mode, a.sha)
            self.base.set(a.space, a.rel, a.sha)
        elif a.kind == DEL_LOCAL:
            local.delete(a.space, a.rel)
            self.base.set(a.space, a.rel, None)
        elif a.kind == DEL_REMOTE:
            self._remote(remote.delete, a.space, a.rel)
            self.base.set(a.space, a.rel, None)
        elif a.kind == MERGE:
            self._do_merge(a)

    def _tee(self, chunks, a: Action):
        """Garde le texte (≤256 Ko) transféré pour pouvoir fusionner plus tard, et surveille l'annulation."""
        buffer, keep = bytearray(), a.size <= BLOB_MAX
        for chunk in chunks:
            self._check()
            if keep:
                buffer += chunk
            yield chunk
        if keep:
            self.base.save_blob(bytes(buffer))

    def _do_merge(self, a: Action) -> None:
        _, ldata = self.local.open_reader(a.space, a.rel)
        _, rdata = self._remote(self.remote.open_reader, a.space, a.rel)
        local_bytes, remote_bytes = b"".join(ldata), b"".join(rdata)
        b = self.base.get(a.space).get(a.rel)
        base = self.base.load_blob(b) if b else None
        if base is None:
            raise SyncPathError("base de fusion introuvable")
        merged, conflict = merge.diff3(base.decode(), local_bytes.decode(), remote_bytes.decode())
        if conflict:
            raise SyncPathError("modifié entre-temps : fusion impossible, réessai au prochain passage")
        data = merged.encode()
        sha = hashlib.sha256(data).hexdigest()
        self.local.write(a.space, a.rel, [data], a.mode, expected_sha=sha)
        self._remote(self.remote.write, a.space, a.rel, len(data), iter([data]), a.mode, sha)
        self.base.set(a.space, a.rel, sha)
        self.base.save_blob(data)

    def _save_conflict_copy(self, a: Action) -> None:
        """Conserve la version perdante à côté du fichier (côté local) avant qu'elle soit écrasée."""
        stamp = time.strftime("%Y%m%d-%H%M%S")
        path = Path(a.rel)
        name = f"{path.stem}{SYNC_CONFLICT}{'distant' if a.loser_remote else self.local_name}-{stamp}{path.suffix}"
        copy_rel = (path.parent / name).as_posix() if str(path.parent) != "." else name
        if a.loser_remote:
            size, chunks = self._remote(self.remote.open_reader, a.space, a.rel)
        else:
            size, chunks = self.local.open_reader(a.space, a.rel)
        self.local.write(a.space, copy_rel, chunks, a.mode)
