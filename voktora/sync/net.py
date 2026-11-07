"""
Voktora — sync.net
Réseau : adresses de cette machine (LAN + Tailscale) et règle « même réseau ».

Un pair est accepté seulement s'il est joignable ET sur le même réseau :
  • Tailscale (100.64.0.0/10) : les deux machines doivent être dans le même tailnet (adresse Tailscale locale) ;
  • LAN privé (10/8, 172.16/12, 192.168/16, lien local) : une de nos interfaces doit être dans son sous-réseau ;
  • boucle locale (127/8) : autorisée (tests, deux sessions sur la même machine) ;
  • toute adresse publique est refusée, dans les deux sens (client et serveur).
Bibliothèque standard uniquement ; la commande `tailscale` est utilisée si elle existe.
"""

from __future__ import annotations

import contextlib
import ipaddress
import json
import shutil
import socket
import subprocess

TAILSCALE_NET = ipaddress.ip_network("100.64.0.0/10")
_PRIVATE = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16")]


def _ip(value: str):
    try:
        return ipaddress.ip_address(value.strip().split("%")[0])
    except ValueError:
        return None


def is_tailscale_ip(value: str) -> bool:
    ip = _ip(value)
    return ip is not None and ip.version == 4 and ip in TAILSCALE_NET


def is_loopback(value: str) -> bool:
    ip = _ip(value)
    return ip is not None and ip.is_loopback


def is_private_lan(value: str) -> bool:
    ip = _ip(value)
    return ip is not None and ip.version == 4 and any(ip in net for net in _PRIVATE)


def is_allowed_address(value: str) -> bool:
    """Adresse autorisée à parler à Voktora Sync (jamais une adresse publique)."""
    return is_loopback(value) or is_tailscale_ip(value) or is_private_lan(value)


def _run(cmd: list[str], timeout: float = 3.0) -> str:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)      # noqa: S603
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout if result.returncode == 0 else ""


def tailscale_ips() -> list[str]:
    exe = shutil.which("tailscale")
    if not exe:
        return []
    return [line.strip() for line in _run([exe, "ip", "-4"]).splitlines() if is_tailscale_ip(line)]


def tailscale_peers() -> list[dict]:
    """Machines du tailnet : [{"name", "ip", "online", "os"}] (liste vide si Tailscale est absent)."""
    exe = shutil.which("tailscale")
    if not exe:
        return []
    try:
        status = json.loads(_run([exe, "status", "--json"]) or "{}")
    except json.JSONDecodeError:
        return []
    peers = []
    for peer in (status.get("Peer") or {}).values():
        ips = [i for i in peer.get("TailscaleIPs", []) if is_tailscale_ip(i)]
        if ips:
            peers.append({"name": peer.get("HostName", ips[0]), "ip": ips[0], "online": bool(peer.get("Online")),
                          "os": peer.get("OS", "")})
    return sorted(peers, key=lambda p: p["name"].lower())


def lan_interfaces() -> list[tuple[str, int]]:
    """[(adresse IPv4, longueur de préfixe)] des interfaces locales."""
    found: list[tuple[str, int]] = []
    out = _run(["ip", "-j", "-4", "addr"]) if shutil.which("ip") else ""
    if out:
        with contextlib.suppress(json.JSONDecodeError):
            for iface in json.loads(out):
                for info in iface.get("addr_info", []):
                    if info.get("family") == "inet" and info.get("local"):
                        found.append((info["local"], int(info.get("prefixlen", 24))))
    if not found:                                          # repli portable : l'adresse de sortie par défaut
        with contextlib.suppress(OSError), socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("10.255.255.255", 1))            # aucun paquet n'est envoyé
            found.append((sock.getsockname()[0], 24))
    return found


def local_addresses() -> dict[str, list[str]]:
    """{"tailscale": [...], "lan": [...]} — adresses utilisables pour l'appairage."""
    ts = tailscale_ips()
    ifaces = lan_interfaces()
    ts += [ip for ip, _ in ifaces if is_tailscale_ip(ip) and ip not in ts]
    return {"tailscale": ts, "lan": [ip for ip, _ in ifaces if is_private_lan(ip)]}


def same_network(peer_ip: str, local: dict[str, list[str]] | None = None,
                 ifaces: list[tuple[str, int]] | None = None) -> bool:
    """True si `peer_ip` est sur un de NOS réseaux (voir règles en tête de module)."""
    ip = _ip(peer_ip)
    if ip is None:
        return False
    if ip.is_loopback:
        return True
    local = local if local is not None else local_addresses()
    if is_tailscale_ip(peer_ip):
        return bool(local.get("tailscale"))
    if is_private_lan(peer_ip):
        for addr, prefix in (ifaces if ifaces is not None else lan_interfaces()):
            with contextlib.suppress(ValueError):
                if ip in ipaddress.ip_network(f"{addr}/{prefix}", strict=False):
                    return True
    return False


def default_hostname() -> str:
    return socket.gethostname().split(".")[0] or "voktora-pc"
