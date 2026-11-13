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

import contextlib
import ipaddress
import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence

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


def _open(provider: dict, method: str, path: str, payload: dict | None, timeout: float, extra_headers: dict | None = None):
    """Ouvre la requête et retourne (réponse, base). Les erreurs HTTP/réseau deviennent des AIError lisibles."""
    base = normalize_host(provider.get("kind", KIND_OPENAI), provider.get("host", ""))
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = _headers(provider, base)
    if extra_headers:
        headers.update(extra_headers)
    request = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        return urllib.request.urlopen(request, timeout=timeout), base          # noqa: S310 — schéma validé plus haut
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


def _request(provider: dict, method: str, path: str, payload: dict | None, timeout: float):
    response, base = _open(provider, method, path, payload, timeout)
    try:
        with response:
            return json.loads(response.read().decode("utf-8"))
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


def generate(provider: dict, prompt: str, timeout: float = DEFAULT_TIMEOUT, max_tokens: int | None = None,
             on_token: Callable[[str], None] | None = None, cancel: Callable[[], bool] | None = None) -> str:
    """Envoie `prompt` au modèle du fournisseur et retourne le texte de la réponse.

    Avec `on_token`, la réponse est lue en flux (SSE / NDJSON) et chaque morceau est transmis dès sa
    réception ; `timeout` devient alors un délai d'INACTIVITÉ (entre deux morceaux), pas une durée totale.
    `cancel()` est consulté en continu : s'il devient vrai, la connexion est fermée et le texte déjà reçu est rendu.
    """
    model = (provider.get("model") or "").strip()
    if not model:
        raise AIError("Aucun modèle sélectionné pour ce fournisseur.")
    if on_token is not None:
        return stream_text(provider, prompt, on_token, timeout, max_tokens, cancel)
    if provider.get("kind") == KIND_OLLAMA:
        try:
            return ollama_client._generate(normalize_host(KIND_OLLAMA, provider.get("host", "")),
                                           model, prompt, timeout, max_tokens)
        except ollama_client.OllamaError as exc:
            raise AIError(str(exc)) from exc
    body: dict = {"model": model, "stream": False, "messages": [{"role": "user", "content": prompt}]}
    if max_tokens:
        body["max_tokens"] = int(max_tokens)
    data = _request(provider, "POST", "/chat/completions", body, timeout)
    try:
        text = _content_text(data["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise AIError("Réponse inattendue du fournisseur (pas de « choices »).") from exc
    return _THINK_RE.sub("", text).strip()


# ──────────────────────────────────────────────
# STREAMING
# ──────────────────────────────────────────────

STREAM_IDLE_TIMEOUT = 300.0     # un modèle peut mettre longtemps à se charger avant le premier morceau


def parse_stream_line(kind: str, line: bytes | str) -> tuple[str, bool]:
    """(texte, terminé) pour une ligne du flux. Ollama : NDJSON ; OpenAI/OmniRoute : SSE « data: {…} »."""
    text = line.decode("utf-8", errors="replace") if isinstance(line, bytes) else line
    text = text.strip()
    if not text or text.startswith(":"):                    # ligne vide / commentaire keep-alive SSE
        return "", False
    if kind != KIND_OLLAMA:
        if not text.startswith("data:"):
            return "", False
        text = text[5:].strip()
        if text == "[DONE]":
            return "", True
    try:
        obj = json.loads(text)
    except ValueError:
        return "", False
    if not isinstance(obj, dict):
        return "", False
    if obj.get("error"):
        err = obj["error"]
        raise AIError(f"Erreur du fournisseur : {(err.get('message') if isinstance(err, dict) else err)!s:.300}")
    if kind == KIND_OLLAMA:
        return str(obj.get("response") or ""), bool(obj.get("done"))
    try:
        choice = obj["choices"][0]
    except (KeyError, IndexError, TypeError):
        return "", False
    delta = choice.get("delta") or choice.get("message") or {}
    return _content_text(delta.get("content")), choice.get("finish_reason") not in (None, "")


def stream_text(provider: dict, prompt: str, on_token: Callable[[str], None], timeout: float = STREAM_IDLE_TIMEOUT,
                max_tokens: int | None = None, cancel: Callable[[], bool] | None = None) -> str:
    """Lit la réponse en flux ; retourne le texte complet (sans les blocs <think>)."""
    kind = provider.get("kind") or KIND_OPENAI
    model = (provider.get("model") or "").strip()
    if kind == KIND_OLLAMA:
        path = "/api/generate"
        body: dict = {"model": model, "prompt": prompt, "stream": True}
        if max_tokens:
            body["options"] = {"num_predict": int(max_tokens)}
    else:
        path = "/chat/completions"
        body = {"model": model, "stream": True, "messages": [{"role": "user", "content": prompt}]}
        if max_tokens:
            body["max_tokens"] = int(max_tokens)
    response, base = _open(provider, "POST", path, body, timeout,
                           {"Accept": "text/event-stream, application/x-ndjson"})
    finished = threading.Event()

    def watch() -> None:                       # une lecture bloquée ne voit pas `cancel` : on ferme la connexion
        while not finished.wait(0.2):
            if cancel is not None and cancel():
                with contextlib.suppress(Exception):
                    response.close()
                return

    if cancel is not None:
        threading.Thread(target=watch, daemon=True, name="voktora-ai-cancel").start()
    parts: list[str] = []
    try:
        with response:
            for raw in response:
                piece, done = parse_stream_line(kind, raw)
                if piece:
                    parts.append(piece)
                    on_token(piece)
                if done:
                    break
    except (TimeoutError, OSError, ValueError) as exc:
        if cancel is not None and cancel():
            pass                               # arrêt demandé : on rend ce qui a été reçu
        elif isinstance(exc, TimeoutError) or "timed out" in str(exc):
            raise AIError(f"Le fournisseur n'a rien envoyé pendant {int(timeout)} s ({base}) : "
                          "modèle trop lent ou bloqué ?") from exc
        else:
            raise AIError(f"Connexion interrompue avec {base} : {exc}") from exc
    finally:
        finished.set()
    return _THINK_RE.sub("", "".join(parts)).strip()


DESCRIPTION_MAX_TOKENS = 220
ICON_MAX_TOKENS = 24
ICON_SHORTLIST = 12          # nombre d'icônes proposées au modèle (au lieu de tout le catalogue)
DIGEST_MAX_CHARS = 700       # taille maximale du contexte envoyé

_NOISE_LINE = re.compile(r"^\s*(\[!\[|!\[|<img|<a |<p |</|<!--|\||[-=*_]{3,}\s*$|```|~~~)")
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")


def project_digest(readme_text: str = "", notes: str = "", entries: Sequence[str] = (),
                   limit: int = DIGEST_MAX_CHARS) -> str:
    """Résumé compact d'un projet pour l'IA : notes + début utile du README + quelques noms de fichiers.

    Les badges, images, tableaux, blocs de code et lignes de liens sont ignorés : ils coûtent des
    jetons (donc du temps de génération) sans rien apprendre au modèle.
    """
    parts: list[str] = []
    if notes.strip():
        parts.append(notes.strip()[:200])
    kept: list[str] = []
    in_fence = False
    for raw in readme_text.splitlines():
        line = raw.strip()
        if line.startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence or not line or _NOISE_LINE.match(raw):
            continue
        line = _MD_LINK.sub(r"\1", line).lstrip("#").strip(" >*-")
        if len(line) > 3:
            kept.append(line)
        if sum(len(k) + 1 for k in kept) >= limit:
            break
    if kept:
        parts.append(" ".join(kept))
    if entries:
        parts.append("Fichiers : " + ", ".join(list(entries)[:10]))
    return "\n".join(parts)[:limit]


def generate_description(provider: dict, project_name: str, context: str = "",
                         timeout: float = DEFAULT_TIMEOUT) -> str:
    """Courte description (2 à 4 phrases, Markdown) d'un projet."""
    prompt = (
        "Décris ce projet logiciel en français, 2 à 3 phrases, Markdown, sans titre ni préambule.\n"
        f"Projet : {project_name}\n"
    )
    if context.strip():
        prompt += f"Contexte : {context.strip()[:DIGEST_MAX_CHARS]}\n"
    text = generate(provider, prompt, timeout, max_tokens=DESCRIPTION_MAX_TOKENS)
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


_WORD = re.compile(r"[a-z0-9]{3,}")


def shortlist_icons(choices: Sequence[str], text: str, keywords: dict[str, str] | None = None,
                    limit: int = ICON_SHORTLIST) -> list[str]:
    """Présélection locale : les `limit` icônes dont l'identifiant/les mots-clés recoupent `text`.

    Évite d'envoyer tout le catalogue au modèle. Sans aucun recoupement, on garde les premières
    icônes du catalogue (ordre stable) pour que le modèle ait toujours un choix.
    """
    words = set(_WORD.findall(text.lower()))
    scored: list[tuple[int, int, str]] = []
    for index, choice in enumerate(choices):
        haystack = set(_WORD.findall(choice.lower().split(":", 1)[-1].replace("-", " ")))
        if keywords:
            haystack |= set(_WORD.findall(keywords.get(choice, "")))
        scored.append((-len(words & haystack), index, choice))
    scored.sort()
    return [choice for _s, _i, choice in scored[:max(1, limit)]]


def suggest_icon(provider: dict, project_name: str, choices: Sequence[str], context: str = "",
                 timeout: float = DEFAULT_TIMEOUT, keywords: dict[str, str] | None = None) -> str:
    """Identifiant d'icône (parmi `choices`) qui représente le mieux le projet.

    Seule une présélection d'une douzaine d'icônes est envoyée, avec un contexte très court.
    """
    short_context = context.strip()[:300]
    candidates = shortlist_icons(choices, f"{project_name} {short_context}", keywords)
    prompt = (
        "Quelle icône représente le mieux ce projet ? Réponds avec UN identifiant de la liste, rien d'autre.\n"
        f"Liste : {', '.join(candidates)}\nProjet : {project_name}\n"
    )
    if short_context:
        prompt += f"Contexte : {short_context}\n"
    answer = generate(provider, prompt, timeout, max_tokens=ICON_MAX_TOKENS)
    icon_id = pick_icon_id(answer, candidates) or pick_icon_id(answer, choices)
    if icon_id is None:
        raise AIError(f"Le fournisseur n'a pas renvoyé d'icône de la liste (réponse reçue : {answer[:80]!r}).")
    return icon_id
