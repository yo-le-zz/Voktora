"""
Voktora — sync.groupsync (1.1.4)
Côté service : état du groupe (mode, chef, époque), propositions avec accord explicite, abdication, diffusion et
« bavardage » (un état d'époque supérieure et autorisé, vu dans /hello, est adopté). Règles pures : roles.py.
Les propositions en attente sont gardées en mémoire (10 min) ; l'état adopté est persisté dans settings.json.
"""

from __future__ import annotations

import contextlib
import time

from . import roles
from .client import RemoteError
from .server import HandlerError


class GroupSync:
    def __init__(self, svc):
        self.svc = svc
        self.mine: dict[str, roles.Proposal] = {}          # propositions que NOUS avons faites
        self.incoming: dict[str, dict] = {}                # propositions reçues, en attente de notre accord

    # ── état ─────────────────────────────────────────────────────────────────

    @property
    def state(self) -> roles.GroupState:
        return roles.GroupState.from_dict(self.svc.settings["group"])

    def members(self) -> set[str]:
        s = self.svc.settings
        return {s.device_id} | {p["id"] for p in s["peers"]}

    def set_state(self, state: roles.GroupState) -> None:
        s = self.svc.settings
        s["group"] = state.to_dict()
        s.save()
        label = roles.MODE_LABELS[state.mode]
        leader = self.name_of(state.leader_id) if state.directed else ""
        self.svc.log(f"Mode du groupe : {label}" + (f", chef : {leader}" if leader else "") + f" (époque {state.epoch})",
                     important=True)
        self.svc._emit(force=True)

    def name_of(self, device_id: str) -> str:
        s = self.svc.settings
        if device_id == s.device_id:
            return s["device_name"] + " (ce PC)"
        return (s.peer(device_id) or {}).get("name", device_id)

    def group_dict(self) -> dict:
        return self.state.to_dict()

    def role_of(self, device_id: str) -> str:
        return roles.role_of(self.state, device_id, self.svc.settings["primary_id"])

    def effective_primary(self) -> str:
        return roles.effective_primary(self.state, self.svc.settings["primary_id"])

    # ── adoption (messages reçus, bavardage) ─────────────────────────────────

    def adopt(self, data, via: str = "") -> bool:
        """Adopte l'état reçu s'il est plus récent ET autorisé. Retourne True si l'état local a changé."""
        incoming = roles.GroupState.from_dict(data)
        local = self.state
        if incoming == local:
            return False
        if incoming.epoch == local.epoch:
            winner = roles.resolve(local, incoming)        # départage déterministe à époque égale
            if winner != local:
                self.set_state(winner)
                return True
            return False
        ok, _why = roles.validate_adoption(local, incoming, self.members())
        if not ok:
            return False
        self.set_state(incoming)
        self.incoming = {k: v for k, v in self.incoming.items() if v["state"].epoch > incoming.epoch}
        self.mine = {k: v for k, v in self.mine.items() if v.state.epoch > incoming.epoch}
        return True

    # ── actions de l'utilisateur ─────────────────────────────────────────────

    def propose(self, mode: str, leader_id: str = "", takeover: bool = False) -> dict:
        """Change le mode / le chef. Immédiat si ce PC est le chef ; sinon demande l'accord explicite des autres PC."""
        s, state = self.svc.settings, self.state
        members = self.members()
        required = roles.required_agreement(state, s.device_id, members, takeover)
        if not required:
            new = roles.propose(state, s.device_id, mode, leader_id, members)
            self.set_state(new)
            return {"adopted": True, "notified": self.broadcast(new)}
        draft = roles.propose(state, s.device_id, mode, leader_id, members, agreed=required, takeover=takeover)
        proposal = roles.Proposal(roles.GroupState(draft.mode, draft.leader_id, draft.epoch, draft.by, (), draft.takeover, draft.ts),
                                  frozenset(required))
        self.mine[proposal.id] = proposal
        sent = []
        for pid in required:
            peer = s.peer(pid)
            if not peer:
                continue
            with contextlib.suppress(ConnectionError, RemoteError):
                if self.svc._remote(peer).roles_propose({"state": proposal.state.to_dict(), "proposal": True}) is not None:
                    sent.append(pid)
        self.svc.log(f"Proposition envoyée ({len(sent)}/{len(required)} PC) : en attente de leur accord explicite", important=True)
        return {"adopted": False, "pending": sorted(required), "proposal": proposal.id, "sent": sent}

    def abdicate(self, successor: str = "") -> dict:
        s = self.svc.settings
        new = roles.abdicate(self.state, s.device_id, self.members(), successor)
        self.set_state(new)
        return {"adopted": True, "notified": self.broadcast(new)}

    def broadcast(self, state: roles.GroupState) -> list[str]:
        """Diffuse un état déjà autorisé (au mieux : les PC injoignables l'apprendront dans /hello)."""
        done = []
        for peer in list(self.svc.settings["peers"]):
            with contextlib.suppress(ConnectionError, RemoteError):
                if self.svc._remote(peer).roles_propose({"state": state.to_dict()}) is not None:
                    done.append(peer["id"])
        return done

    def pending_incoming(self) -> list[dict]:
        now = time.time()
        self.incoming = {k: v for k, v in self.incoming.items() if now - v["received"] < roles.PROPOSAL_TTL}
        return [{"id": k, "from": v["from"], "name": self.name_of(v["from"]), "mode": v["state"].mode,
                 "leader": self.name_of(v["state"].leader_id) if v["state"].directed else "", "takeover": v["state"].takeover}
                for k, v in self.incoming.items()]

    def accept(self, proposal_id: str) -> dict:
        """Donne notre accord explicite à une proposition reçue."""
        item = self.incoming.get(proposal_id)
        if not item:
            raise ValueError("Proposition introuvable ou expirée.")
        peer = self.svc.settings.peer(item["from"])
        reply = self.svc._remote(peer).roles_accept({"id": proposal_id})
        if reply is None:
            raise ConnectionError("L'autre PC ne gère pas les rôles (version plus ancienne).")
        self.incoming.pop(proposal_id, None)
        return reply

    def decline(self, proposal_id: str) -> None:
        self.incoming.pop(proposal_id, None)
        self.svc._emit(force=True)

    # ── serveur ──────────────────────────────────────────────────────────────

    def on_propose(self, device: str, body: dict) -> dict:
        incoming = roles.GroupState.from_dict(body.get("state"))
        if self.adopt(incoming.to_dict(), via=device):
            return {"adopted": True}
        local = self.state
        if body.get("proposal") and incoming.by == device and incoming.epoch > local.epoch:
            ok, why = roles.validate_adoption(local, incoming, self.members())
            if not ok and why == "accord insuffisant" and self.svc.settings.device_id in \
                    roles.required_agreement(local, device, self.members(), incoming.takeover):
                proposal = roles.Proposal(incoming, frozenset())
                self.incoming[proposal.id] = {"state": incoming, "from": device, "received": time.time()}
                self.svc.log(f"{self.name_of(device)} propose un changement de rôles : votre accord est demandé", device,
                             important=True)
                self.svc._emit(force=True)
                return {"adopted": False, "pending": True, "id": proposal.id}
        if incoming.epoch <= local.epoch:
            return {"adopted": False, "stale": True, "group": local.to_dict()}
        raise HandlerError(409, "Proposition refusée : accord insuffisant ou auteur non autorisé.")

    def on_accept(self, device: str, body: dict) -> dict:
        proposal = self.mine.get(str(body.get("id", "")))
        if not proposal or proposal.expired():
            raise HandlerError(404, "Proposition inconnue ou expirée.")
        if device not in proposal.required:
            raise HandlerError(403, "Votre accord n'est pas requis.")
        if proposal.agree(device):
            final = proposal.final_state()
            self.mine.pop(proposal.id, None)
            self.set_state(final)
            return {"ok": True, "complete": True, "notified": self.broadcast(final)}
        return {"ok": True, "complete": False}
