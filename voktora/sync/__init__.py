"""
Voktora — sync
Synchronisation entre vos PC (principal ↔ portable…) : configuration, métadonnées des projets et fichiers des
projets, UNIQUEMENT quand les deux machines sont sur le même réseau (LAN ou Tailscale).

Principe : le PC « principal » fait autorité en cas de conflit ; un PC « secondaire » se synchronise vers lui
automatiquement dès qu'il le voit, s'arrête quand l'un des deux s'éteint et reprend au prochain démarrage.
Modules : net (réseau), secure (chiffrement/signature), merge (fusion 3 voies), settings, store (fichiers),
engine (plan + application), server/client (protocole), service (surveillance et statut).
"""

from .appio import get_service
from .engine import Plan, SyncEngine
from .service import SyncService
from .settings import SyncSettings

__all__ = ["get_service", "Plan", "SyncEngine", "SyncService", "SyncSettings"]
