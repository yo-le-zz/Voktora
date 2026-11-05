"""
Voktora — ai_providers.py
Fournisseurs d'IA pour générer des descriptions de projet et suggérer des icônes.

Trois types de fournisseurs :

  ollama     serveur Ollama (API native /api/…), local par défaut : http://localhost:11434 ;
  omniroute  passerelle OmniRoute (API compatible OpenAI), par défaut http://localhost:20128/v1 ;
  openai     tout serveur compatible OpenAI : LM Studio, vLLM, llama.cpp, OpenRouter, Groq, OpenAI…

Chaque fournisseur est un dict `{id, kind, name, host, model, api_key}` enregistré dans la
configuration (voir core.config_store.get_ai_config). Plusieurs fournisseurs peuvent coexister ;
l'un d'eux est « actif ».

Sécurité :
  • seuls les schémas http et https sont acceptés (jamais file:, ftp:…) ;
  • une clé d'API n'est envoyée en clair (http) que vers la machine locale ou un réseau privé :
    vers un hôte public, https est obligatoire ;
  • les messages d'erreur ne contiennent jamais la clé d'API.

Tous les appels sont bloquants : à lancer dans un thread de travail.
"""

from __future__ import annotations

import ipaddress
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence

import core
import ollama_client

KIND_OLLAMA = "ollama"
KIND_OMNIROUTE = "omniroute"
KIND_OPENAI = "openai"
KINDS = (KIND_OLLAMA, KIND_OMNIROUTE, KIND_OPENAI)

KIND_LABELS = {
    KIND_OLLAMA: "Ollama",
    KIND_OMNIROUTE: "OmniRoute",
    KIND_OPENAI: "Compatible OpenAI (LM Studio, vLLM, OpenRouter…)",
}
DEFAULT_HOSTS = {
    KIND_OLLAMA: "http://localhost:11434",
    KIND_OMNIROUTE: "http://localhost:20128/v1",
    KIND_OPENAI: "http://localhost:1234/v1",
}

DEFAULT_TIMEOUT = 60.0
_ERROR_EXCERPT = 300
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


class AIError(RuntimeError):
    """Erreur de communication avec un fournisseur d'IA, ou réponse inexploitable."""


# ──────────────────────────────────────────────
# URL ET SÉCURITÉ
# ──────────────────────────────────────────────

def _is_private_host(hostname: str) -> bool:
    host = hostname.strip("[]").lower()
    if host in ("localhost", "") or host.endswith((".localhost", ".local", ".lan", ".internal", ".home.arpa")):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return "." not in host            # nom court (hôte du réseau local, conteneur Docker…)
    return address.is_loopback or address.is_private or address.is_link_local


def normalize_host(kind: str, host: str) -> str:
    """URL de base propre : schéma validé, sans « / » final ; « /v1 » ajouté pour les API OpenAI."""
    host = (host or "").strip() or DEFAULT_HOSTS.get(kind, "")
    if "://" not in host:
        host = "http://" + host
    parsed = urllib.parse.urlparse(host)
    try:
        _ = parsed.port                    # lève ValueError si le port n'est pas un nombre valide
    except ValueError:
        parsed = parsed._replace(netloc="")
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise AIError(f"Adresse invalide : « {host} » (attendu : http://hôte:port ou https://…).")
    path = parsed.path.rstrip("/")
    if kind in (KIND_OMNIROUTE, KIND_OPENAI) and not path:
        path = "/v1"
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))


def _headers(provider: dict, base: str) -> dict:
    headers = {"Content-Type": "application/json", "Accept": "application/json",
               "User-Agent": f"{core.APP_NAME}/{core.APP_VERSION}"}
    key = (provider.get("api_key") or "").strip()
    if key:
        parsed = urllib.parse.urlparse(base)
        if parsed.scheme != "https" and not _is_private_host(parsed.hostname or ""):
            raise AIError("Clé d'API refusée en clair : utilisez https:// pour un serveur hors de votre réseau local.")
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _request(provider: dict, method: str, path: str, payload: dict | None, timeout: float):
    base = normalize_host(provider.get("kind", KIND_OPENAI), provider.get("host", ""))
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(base + path, data=data, headers=_headers(provider, base), method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:_ERROR_EXCERPT]
        if exc.code in (401, 403):
            raise AIError(f"Accès refusé par {provider.get('name') or base} ({exc.code}) : "
                          "vérifiez la clé d'API.") from exc
        if exc.code == 404:
            raise AIError(f"Point d'accès introuvable ({base}{path}) : vérifiez l'adresse et le type "
                          f"de fournisseur. {body}") from exc
        raise AIError(f"Erreur du fournisseur ({exc.code}) : {body}") from exc
    except urllib.error.URLError as exc:
        raise AIError(f"Impossible de contacter {base} — le serveur est-il lancé ? Détail : {exc.reason}") from exc
    except (TimeoutError, OSError) as exc:
        raise AIError(f"Erreur réseau vers {base} : {exc}") from exc
    except json.JSONDecodeError as exc:
        raise AIError(f"Réponse illisible de {base} : {exc}") from exc


# ──────────────────────────────────────────────
# OPÉRATIONS
# ──────────────────────────────────────────────

def is_available(provider: dict, timeout: float = 3.0) -> bool:
    try:
        list_models(provider, timeout=timeout)
    except AIError:
        return False
    return True


def list_models(provider: dict, timeout: float = 10.0) -> list[str]:
    """Modèles proposés par le fournisseur (installés pour Ollama, routés pour OmniRoute)."""
    if provider.get("kind") == KIND_OLLAMA:
        try:
            return ollama_client.list_models(normalize_host(KIND_OLLAMA, provider.get("host", "")), timeout)
        except ollama_client.OllamaError as exc:
            raise AIError(str(exc)) from exc
    data = _request(provider, "GET", "/models", None, timeout)
    items = data.get("data", []) if isinstance(data, dict) else []
    return sorted({m["id"] for m in items if isinstance(m, dict) and m.get("id")})


def _content_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):          # certains routeurs renvoient une liste de parties
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return ""


def generate(provider: dict, prompt: str, timeout: float = DEFAULT_TIMEOUT) -> str:
    """Envoie `prompt` au modèle du fournisseur et retourne le texte de la réponse."""
    model = (provider.get("model") or "").strip()
    if not model:
        raise AIError("Aucun modèle sélectionné pour ce fournisseur.")
    if provider.get("kind") == KIND_OLLAMA:
        try:
            return ollama_client._generate(normalize_host(KIND_OLLAMA, provider.get("host", "")),
                                           model, prompt, timeout)
        except ollama_client.OllamaError as exc:
            raise AIError(str(exc)) from exc
    data = _request(provider, "POST", "/chat/completions", {
        "model": model, "stream": False,
        "messages": [{"role": "user", "content": prompt}],
    }, timeout)
    try:
        text = _content_text(data["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise AIError("Réponse inattendue du fournisseur (pas de « choices »).") from exc
    return _THINK_RE.sub("", text).strip()


def generate_description(provider: dict, project_name: str, context: str = "",
                         timeout: float = DEFAULT_TIMEOUT) -> str:
    """Courte description (2 à 4 phrases, Markdown) d'un projet."""
    prompt = (
        "Tu es un assistant qui rédige des descriptions courtes et claires "
        "pour des projets logiciels. Réponds uniquement en français, en "
        "Markdown, en 2 à 4 phrases maximum, sans préambule ni titre.\n\n"
        f"Nom du projet : {project_name}\n"
    )
    if context.strip():
        prompt += f"Contexte disponible (README, fichiers...) :\n{context.strip()[:4000]}\n\n"
    prompt += "Rédige la description :"
    text = generate(provider, prompt, timeout)
    if not text:
        raise AIError("Le fournisseur a renvoyé une réponse vide.")
    return text


def pick_icon_id(answer: str, choices: Sequence[str]) -> str | None:
    """Premier identifiant de `choices` présent dans la réponse (insensible à la casse, mot entier)."""
    lowered = answer.lower()
    best: tuple[int, str] | None = None
    for choice in choices:
        match = re.search(rf"(?<![\w-]){re.escape(choice.lower())}(?![\w-])", lowered)
        if match and (best is None or match.start() < best[0]):
            best = (match.start(), choice)
    return best[1] if best else None


def suggest_icon(provider: dict, project_name: str, choices: Sequence[str], context: str = "",
                 timeout: float = DEFAULT_TIMEOUT) -> str:
    """Identifiant d'icône (parmi `choices`) qui représente le mieux le projet."""
    prompt = (
        "Choisis l'icône qui représente le mieux le projet ci-dessous. Réponds UNIQUEMENT avec UN "
        "identifiant pris tel quel dans cette liste, sans aucun autre texte :\n"
        f"{', '.join(choices)}\n\nNom du projet : {project_name}\n"
    )
    if context.strip():
        prompt += f"Contexte : {context.strip()[:1000]}\n"
    prompt += "Identifiant :"
    answer = generate(provider, prompt, timeout)
    icon_id = pick_icon_id(answer, choices)
    if icon_id is None:
        raise AIError(f"Le fournisseur n'a pas renvoyé d'icône de la liste (réponse reçue : {answer[:80]!r}).")
    return icon_id
