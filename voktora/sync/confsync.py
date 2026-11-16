"""
Voktora — sync.confsync (1.1.4)
Côté service : « Push config », boîte de réception des configurations reçues, aperçu, application, demandes d'un suiveur
au chef, référence de groupe et règle de blocage. Le réseau passe par les mécanismes existants (requêtes signées HMAC +
corps chiffrés AES-GCM, voir secure.py/client.py/server.py). Les règles pures sont dans configpack.py et roles.py.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import time
from pathlib import Path

from . import configpack as cp
from . import roles
from .client import RemoteError
from .server import HandlerError


class ConfigSync:
    def __init__(self, svc):
        self.svc = svc
        self.env = cp.ConfigEnv(svc.data_dir, svc.store.config_io)
        self.inbox_dir = svc.dir / "config-inbox"
        self.requests_dir = svc.dir / "config-requests"
        self.backups_dir = svc.dir / "config-backups"
        self._cache: tuple[float, dict] | None = None

    # ── paquet local et révision ─────────────────────────────────────────────

    def invalidate(self) -> None:
        self._cache = None

    def local_pack(self, fresh: bool = False) -> dict:
        now = time.monotonic()
        if not fresh and self._cache and now - self._cache[0] < 3.0:
            return self._cache[1]
        s = self.svc.settings
        pack = cp.build_pack(self.env, s.device_id, s["device_name"], self._app_version())
        self._cache = (now, pack)
        return pack

    @staticmethod
    def _app_version() -> str:
        try:
            import core
            return str(core.APP_VERSION)
        except Exception:  # noqa: BLE001
            return ""

    def local_info(self) -> cp.RevInfo:
        s = self.svc.settings
        return cp.RevInfo(self.local_pack()["rev"], s["applied_rev"], s["applied_local_rev"])

    def hello_info(self) -> dict:
        info = self.local_info()
        return {"rev": info.rev, "applied_rev": info.applied_rev, "applied_local_rev": info.applied_local_rev,
                "ref": self.svc.settings["config_ref"] or None, "pending": len(self.inbox())}

    # ── référence de groupe ──────────────────────────────────────────────────

    def ref(self) -> cp.ConfigRef | None:
        return cp.ConfigRef.from_dict(self.svc.settings["config_ref"])

    def adopt_ref(self, data) -> None:
        theirs = cp.ConfigRef.from_dict(data)
        best = cp.newest_ref(self.ref(), theirs)
        if best is not None and best != self.ref():
            self.svc.settings["config_ref"] = best.to_dict()
            self.svc.settings.save()

    def gate(self, peer_id: str, info: dict) -> cp.GateResult:
        """Règle de blocage entre ce PC et `peer_id` (`info` = réponse /hello ou /config/rev du pair)."""
        s, group = self.svc.settings, self.svc.groups.state
        remote_cfg = info.get("config") if isinstance(info.get("config"), dict) else (info if "rev" in info else None)
        remote = cp.RevInfo.from_dict(remote_cfg)
        if isinstance(remote_cfg, dict):
            self.adopt_ref(remote_cfg.get("ref"))
        peer = s.peer(peer_id) or {}
        return cp.evaluate_gate(enabled=bool(s["config_gate"]), directed=group.directed, my_id=s.device_id, peer_id=peer_id,
                                leader_id=group.leader_id, local=self.local_info(), remote=remote, ref=self.ref(),
                                peer_name=peer.get("name", "l'autre PC"))

    def check_lock(self, device: str, body: dict) -> None:
        """Côté serveur : un pair qui annonce une configuration divergente ne peut pas verrouiller ce PC."""
        cfg = body.get("config") if isinstance(body, dict) else None
        remote = cp.RevInfo.from_dict(cfg)
        if remote is None:
            return                                        # pair ancien : non vérifiable, comportement historique
        result = self.gate(device, {"config": cfg})
        if not result.ok:
            raise HandlerError(409, result.message)

    # ── push ─────────────────────────────────────────────────────────────────

    def push(self, peer_id: str) -> dict:
        """« Push config » vers un pair. En mode dirigé, un suiveur envoie une demande au chef à la place."""
        svc, s = self.svc, self.svc.settings
        peer = s.peer(peer_id)
        if not peer:
            raise ValueError("PC inconnu.")
        mode, why = roles.can_push_config(svc.groups.state, s.device_id)
        if mode == "request":
            return {"mode": "request", "message": why, **self.request(peer_id)}
        remote = svc._remote(peer)
        theirs = remote.config_rev()
        if theirs is None:
            raise ConnectionError(f"« {peer['name']} » utilise une version sans « Push config » : mettez-le à jour.")
        pack = self.local_pack(fresh=True)
        seq = max((self.ref() or cp.ConfigRef("")).seq, (cp.ConfigRef.from_dict(theirs.get("ref")) or cp.ConfigRef("")).seq) + 1
        ref = cp.ConfigRef(pack["rev"], seq, s.device_id, s["device_name"], time.time())
        reply = remote.config_push({"pack": pack, "ref": ref.to_dict(), "group": svc.groups.state.to_dict()})
        if reply is None:
            raise ConnectionError("Push config non pris en charge par l'autre PC.")
        s["config_ref"] = ref.to_dict()
        s.save()
        svc.log(f"Push config envoyé à {peer['name']} (révision {pack['rev'][:8]}, {len(pack['files'])} fichier(s))", peer_id,
                important=True)
        svc.control.unblock(peer_id)
        svc._emit(force=True)
        return {"mode": "direct", "rev": pack["rev"], **reply}

    def push_all(self) -> dict[str, dict | str]:
        out: dict[str, dict | str] = {}
        for peer in list(self.svc.settings["peers"]):
            try:
                out[peer["id"]] = self.push(peer["id"])
            except (ConnectionError, RemoteError, ValueError) as exc:
                out[peer["id"]] = f"échec : {exc}"
        return out

    # ── réception (serveur) ──────────────────────────────────────────────────

    def on_push(self, device: str, body: dict) -> dict:
        svc, s = self.svc, self.svc.settings
        incoming_group = roles.GroupState.from_dict(body.get("group"))
        svc.groups.adopt(incoming_group.to_dict(), via=device)
        ok, why = roles.accept_push(svc.groups.state, s.device_id, device, incoming_group.epoch)
        if not ok:
            raise HandlerError(409, why)
        try:
            pack = cp.verify_pack(body.get("pack"))
        except cp.PackError as exc:
            raise HandlerError(400, str(exc)) from exc
        ref = cp.ConfigRef.from_dict(body.get("ref"))
        if ref and ref.rev == pack["rev"]:
            self.adopt_ref(ref.to_dict())
        name = (s.peer(device) or {}).get("name", device)
        if pack["rev"] == self.local_pack(fresh=True)["rev"]:
            svc.log(f"Push config de {name} : déjà identique", device)
            return {"accepted": True, "already": True}
        self._write_json(self.inbox_dir / f"{device}.json", pack)
        svc.log(f"Configuration reçue de {name} (révision {pack['rev'][:8]}) : à appliquer depuis la fenêtre de synchronisation",
                device, important=True)
        svc._emit(force=True)
        return {"accepted": True, "queued": True}

    @staticmethod
    def _write_json(path: Path, data) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False)
            with contextlib.suppress(OSError):
                os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    # ── boîte de réception, aperçu, application ──────────────────────────────

    def inbox(self) -> list[dict]:
        out = []
        for path in sorted(self.inbox_dir.glob("*.json")) if self.inbox_dir.is_dir() else []:
            try:
                pack = json.loads(path.read_text(encoding="utf-8"))
                out.append({"from": path.stem, "name": (self.svc.settings.peer(path.stem) or {}).get("name", path.stem),
                            "rev": str(pack.get("rev", "")), "received": path.stat().st_mtime,
                            "files": len(pack.get("files", {}))})
            except (OSError, ValueError):
                continue
        return out

    def load_inbox(self, peer_id: str) -> dict:
        try:
            pack = json.loads((self.inbox_dir / f"{peer_id}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError("Aucune configuration reçue de ce PC.") from exc
        return cp.verify_pack(pack)                        # re-vérifié : le fichier a pu être modifié sur le disque

    def discard(self, peer_id: str) -> None:
        with contextlib.suppress(OSError):
            (self.inbox_dir / f"{peer_id}.json").unlink()
        self.svc._emit(force=True)

    def preview(self, peer_id: str) -> cp.ConfigDiff:
        return cp.diff_packs(self.local_pack(fresh=True), self.load_inbox(peer_id))

    def apply(self, peer_id: str, allow_hooks: bool = False, install_plugins: bool = False, installer=None) -> cp.ApplyResult:
        svc, s = self.svc, self.svc.settings
        if svc.is_busy():
            raise RuntimeError("Une synchronisation est en cours : attendez la fin (ou mettez en pause/arrêtez).")
        pack = self.load_inbox(peer_id)
        result = cp.apply_pack(self.env, pack, cp.ApplyOptions(allow_hooks=allow_hooks, install_plugins=install_plugins,
                                                               installer=installer, backups_dir=self.backups_dir))
        self.invalidate()
        if result.ok:
            s["applied_rev"], s["applied_local_rev"] = pack["rev"], result.new_rev
            s.save()
            self.discard(peer_id)
            svc.control.unblock()
            svc.log(f"Configuration appliquée ({result.changes} changement(s)) — sauvegarde : {Path(result.backup).name}",
                    important=True)
            svc._event("on_config_applied", rev=pack["rev"][:8], changes=result.changes)
        else:
            svc.log(f"Application de la configuration refusée : {result.error}"
                    + (" — ancienne configuration restaurée" if result.rolled_back else ""), important=True)
        svc._emit(force=True)
        return result

    def fetch_from(self, peer_id: str) -> dict:
        """Récupère la configuration d'un pair (le chef, ou « celle du groupe ») dans la boîte de réception."""
        peer = self.svc.settings.peer(peer_id)
        if not peer:
            raise ValueError("PC inconnu.")
        pack = self.svc._remote(peer).config_pack()
        if pack is None:
            raise ConnectionError("Cet autre PC n'a pas « Push config » (version plus ancienne).")
        pack = cp.verify_pack(pack)
        self._write_json(self.inbox_dir / f"{peer_id}.json", pack)
        info = self.svc._remote(peer).config_rev() or {}
        self.adopt_ref(info.get("ref"))
        self.svc._emit(force=True)
        return {"rev": pack["rev"]}

    def pack_for(self, device: str) -> dict:
        return self.local_pack(fresh=True)

    # ── demandes d'un suiveur au chef ────────────────────────────────────────

    def request(self, peer_id: str) -> dict:
        peer = self.svc.settings.peer(peer_id)
        pack = self.local_pack(fresh=True)
        remote = self.svc._remote(peer)
        theirs = remote.config_pack()
        summary = cp.diff_packs(cp.verify_pack(theirs), pack).summary() if theirs else ""
        reply = remote.config_request({"rev": pack["rev"], "files": len(pack["files"]), "summary": summary,
                                       "group": self.svc.groups.state.to_dict()})
        if reply is None:
            raise ConnectionError("Demande non prise en charge par l'autre PC.")
        self.svc.log(f"Demande de push envoyée à {peer['name']} (en attente de sa décision)", peer_id, important=True)
        return {"requested": True}

    def on_request(self, device: str, body: dict) -> dict:
        s = self.svc.settings
        ok, why = roles.fence(self.svc.groups.state, roles.GroupState.from_dict(body.get("group")).epoch)
        if not ok:
            raise HandlerError(409, why)
        name = (s.peer(device) or {}).get("name", device)
        self._write_json(self.requests_dir / f"{device}.json", {"rev": str(body.get("rev", "")), "files": int(body.get("files", 0) or 0),
                                                                "summary": str(body.get("summary", ""))[:300], "ts": time.time()})
        self.svc.log(f"{name} demande l'adoption de sa configuration", device, important=True)
        self.svc._emit(force=True)
        return {"received": True}

    def requests(self) -> list[dict]:
        out = []
        for path in sorted(self.requests_dir.glob("*.json")) if self.requests_dir.is_dir() else []:
            with contextlib.suppress(OSError, ValueError):
                data = json.loads(path.read_text(encoding="utf-8"))
                out.append({"from": path.stem, "name": (self.svc.settings.peer(path.stem) or {}).get("name", path.stem), **data})
        return out

    def accept_request(self, device: str) -> dict:
        """Le chef accepte : il récupère la configuration du suiveur (aperçu puis application comme d'habitude)."""
        result = self.fetch_from(device)
        with contextlib.suppress(OSError):
            (self.requests_dir / f"{device}.json").unlink()
        return result

    def decline_request(self, device: str) -> None:
        with contextlib.suppress(OSError):
            (self.requests_dir / f"{device}.json").unlink()
        self.svc._emit(force=True)
