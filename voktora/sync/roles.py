"""
Voktora — sync.roles (1.1.4)
Modes de groupe et élection du chef. Logique pure (aucun Qt, réseau ou disque).

  • « Égalitaire » : comportement historique (PC principal = priorité en cas de conflit).
  • « Dirigé »     : un PC « chef » (leader) est la source de vérité ; les autres sont « suiveurs ».

Anti split-brain : chaque changement d'état du groupe incrémente un numéro d'ÉPOQUE (epoch). L'état d'époque la plus élevée
gagne ; à époque égale, un départage déterministe est appliqué (`resolve`). Un message d'un chef d'époque périmée est refusé
(`fence`) : il apprend alors l'état courant et perd son rôle.

Autorité d'un changement (désignation, changement, abdication) :
  • le chef actuel peut tout changer seul ;
  • sinon (mode égalitaire, ou prise de direction) il faut l'accord explicite de TOUS les autres membres
    (`agreed_by`) ; avec `takeover=True` le chef actuel, injoignable, n'est pas compté.
Limite assumée : chaque paire de PC a son propre secret ; l'accord n'est donc pas une preuve cryptographique transférable
à un troisième PC — les membres appairés se font confiance (voir doc/SYNC.md).
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field

EGALITARIAN, DIRECTED = "egalitarian", "directed"
MODE_LABELS = {EGALITARIAN: "Égalitaire", DIRECTED: "Dirigé"}
ROLE_LABELS = {"leader": "👑 chef", "follower": "suiveur", "primary": "principal", "secondary": "secondaire"}
PROPOSAL_TTL = 600.0


class RoleError(ValueError):
    """Changement de rôle refusé (message affichable)."""


@dataclass(frozen=True)
class GroupState:
    mode: str = EGALITARIAN
    leader_id: str = ""
    epoch: int = 0
    by: str = ""
    agreed_by: tuple[str, ...] = ()
    takeover: bool = False
    ts: float = 0.0

    def to_dict(self) -> dict:
        return {"mode": self.mode, "leader_id": self.leader_id, "epoch": self.epoch, "by": self.by,
                "agreed_by": list(self.agreed_by), "takeover": self.takeover, "ts": self.ts}

    @classmethod
    def from_dict(cls, data) -> GroupState:
        if not isinstance(data, dict):
            return cls()
        mode = data.get("mode") if data.get("mode") in (EGALITARIAN, DIRECTED) else EGALITARIAN
        try:
            epoch = max(0, int(data.get("epoch", 0)))
        except (TypeError, ValueError):
            epoch = 0
        leader = str(data.get("leader_id") or "")
        if mode == EGALITARIAN:
            leader = ""
        agreed = data.get("agreed_by") or []
        agreed = tuple(sorted({str(a) for a in agreed})) if isinstance(agreed, list | tuple) else ()
        try:
            ts = float(data.get("ts", 0))
        except (TypeError, ValueError):
            ts = 0.0
        return cls(mode, leader, epoch, str(data.get("by") or ""), agreed, bool(data.get("takeover")), ts)

    @property
    def directed(self) -> bool:
        return self.mode == DIRECTED and bool(self.leader_id)


def required_agreement(state: GroupState, actor: str, members: set[str], takeover: bool = False) -> set[str]:
    """Membres dont l'accord explicite est nécessaire pour que `actor` change l'état."""
    if state.directed and actor == state.leader_id:
        return set()
    required = set(members) - {actor}
    if takeover and state.directed:
        required.discard(state.leader_id)
    return required


def propose(state: GroupState, actor: str, mode: str, leader_id: str, members: set[str],
            agreed=(), takeover: bool = False, now: float | None = None) -> GroupState:
    """Nouvel état (époque + 1). Lève RoleError si `actor` n'a pas l'autorité (accord manquant)."""
    members = set(members) | {actor}
    if mode not in (EGALITARIAN, DIRECTED):
        raise RoleError("Mode inconnu.")
    if mode == DIRECTED and leader_id not in members:
        raise RoleError("Le chef doit être l'un des PC du groupe.")
    if mode == EGALITARIAN:
        leader_id = ""
    if mode == state.mode and leader_id == (state.leader_id if state.directed else ""):
        raise RoleError("Cet état est déjà en vigueur.")
    missing = required_agreement(state, actor, members, takeover) - set(agreed)
    if missing:
        raise RoleError(f"Accord explicite manquant de {len(missing)} PC.")
    return GroupState(mode, leader_id, state.epoch + 1, actor, tuple(sorted(set(agreed))), bool(takeover and state.directed),
                      time.time() if now is None else now)


def abdicate(state: GroupState, actor: str, members: set[str], successor: str = "",
             now: float | None = None) -> GroupState:
    """Le chef abdique : un successeur (membre du groupe) ou retour au mode égalitaire."""
    if not (state.directed and state.leader_id == actor):
        raise RoleError("Seul le chef peut abdiquer.")
    if successor:
        if successor == actor or successor not in members:
            raise RoleError("Successeur invalide.")
        return propose(state, actor, DIRECTED, successor, members, now=now)
    return propose(state, actor, EGALITARIAN, "", members, now=now)


def validate_adoption(local: GroupState, incoming: GroupState, members: set[str]) -> tuple[bool, str]:
    """Faut-il adopter `incoming` ? (ok, raison). Vérifie époque, appartenance et autorité."""
    if incoming.epoch <= local.epoch:
        return False, "époque périmée ou identique"
    if incoming.by and incoming.by not in members:
        return False, "auteur inconnu du groupe"
    if incoming.mode == DIRECTED and incoming.leader_id not in members:
        return False, "chef inconnu du groupe"
    if local.directed and incoming.by == local.leader_id:
        return True, "décision du chef"
    needed = required_agreement(local, incoming.by, members, incoming.takeover)
    if needed - set(incoming.agreed_by):
        return False, "accord insuffisant"
    return True, "accord de tous les membres"


def resolve(a: GroupState, b: GroupState) -> GroupState:
    """Époque la plus élevée gagne ; à égalité, départage déterministe (dirigé avant égalitaire, puis plus petit identifiant)."""
    if a.epoch != b.epoch:
        return a if a.epoch > b.epoch else b
    key = lambda s: (0 if s.directed else 1, s.leader_id, s.by)    # noqa: E731
    return a if key(a) <= key(b) else b


def fence(local: GroupState, claimed_epoch: int, claimed_leader: str = "") -> tuple[bool, str]:
    """Un message d'un chef d'époque périmée est refusé."""
    if claimed_epoch < local.epoch:
        return False, f"chef périmé (époque {claimed_epoch} < {local.epoch})"
    if claimed_epoch == local.epoch and local.directed and claimed_leader and claimed_leader != local.leader_id:
        return False, "un autre PC est chef à cette époque"
    return True, ""


def role_of(state: GroupState, device_id: str, primary_id: str = "") -> str:
    if state.directed:
        return "leader" if state.leader_id == device_id else "follower"
    return "primary" if primary_id == device_id else "secondary"


def effective_primary(state: GroupState, primary_id: str) -> str:
    """PC qui gagne les conflits : le chef en mode dirigé, sinon le principal."""
    return state.leader_id if state.directed else primary_id


def can_push_config(state: GroupState, actor: str) -> tuple[str, str]:
    """('direct' | 'request', raison) : un suiveur ne pousse pas de configuration, il la demande au chef."""
    if state.directed and actor != state.leader_id:
        return "request", "Mode dirigé : un suiveur envoie une demande au chef."
    return "direct", ""


def accept_push(state: GroupState, me: str, sender: str, claimed_epoch: int) -> tuple[bool, str]:
    """Côté destinataire : le push de `sender` est-il recevable ?"""
    ok, why = fence(state, claimed_epoch, sender if state.directed else "")
    if not ok:
        return False, why
    if state.directed and sender != state.leader_id:
        if me == state.leader_id:
            return False, "Mode dirigé : le chef n'accepte pas de push, seulement des demandes."
        return False, "Mode dirigé : seule la configuration du chef est acceptée."
    return True, ""


@dataclass
class Proposal:
    state: GroupState
    required: frozenset[str]
    agreed: set[str] = field(default_factory=set)
    created: float = field(default_factory=time.time)

    @property
    def id(self) -> str:
        s = self.state
        return hashlib.sha1(f"{s.epoch}|{s.by}|{s.mode}|{s.leader_id}|{s.takeover}".encode()).hexdigest()[:12]

    def expired(self, now: float | None = None) -> bool:
        return (time.time() if now is None else now) - self.created > PROPOSAL_TTL

    def agree(self, device: str) -> bool:
        """Enregistre l'accord de `device` ; True quand tous les accords requis sont réunis."""
        if device in self.required:
            self.agreed.add(device)
        return self.complete

    @property
    def complete(self) -> bool:
        return self.required <= self.agreed

    def final_state(self) -> GroupState:
        s = self.state
        return GroupState(s.mode, s.leader_id, s.epoch, s.by, tuple(sorted(self.agreed)), s.takeover, s.ts)
