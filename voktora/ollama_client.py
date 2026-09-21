"""
Voktora — ollama_client.py
Intégration avec un serveur Ollama local (https://ollama.com) pour
générer des descriptions de projet et suggérer des emojis pertinents.

Tout reste local : les requêtes vont uniquement vers l'hôte Ollama
configuré (par défaut http://localhost:11434, sur la machine de
l'utilisateur) — aucune donnée n'est envoyée à un service tiers.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_TIMEOUT = 30.0


class OllamaError(RuntimeError):
    """Erreur de communication avec le serveur Ollama, ou réponse inexploitable."""


def is_available(host: str = DEFAULT_HOST, timeout: float = 2.0) -> bool:
    """Teste rapidement si un serveur Ollama répond à `host`."""
    try:
        req = urllib.request.Request(f"{host.rstrip('/')}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def list_models(host: str = DEFAULT_HOST, timeout: float = 5.0) -> list[str]:
    """Liste les modèles installés localement sur le serveur Ollama."""
    req = urllib.request.Request(f"{host.rstrip('/')}/api/tags", method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise OllamaError(
            f"Impossible de contacter Ollama sur {host} — vérifiez qu'il est "
            f"lancé (`ollama serve`). Détail : {exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise OllamaError(f"Réponse Ollama invalide : {exc}") from exc
    return [m.get("name", "") for m in data.get("models", []) if m.get("name")]


def _generate(host: str, model: str, prompt: str, timeout: float) -> str:
    """Appel bas niveau à /api/generate en mode non-streaming."""
    if not model:
        raise OllamaError("Aucun modèle Ollama sélectionné.")
    payload = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode("utf-8")
    req = urllib.request.Request(
        f"{host.rstrip('/')}/api/generate", data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise OllamaError(f"Erreur Ollama ({exc.code}) : {body}") from exc
    except urllib.error.URLError as exc:
        raise OllamaError(
            f"Impossible de contacter Ollama sur {host} — vérifiez qu'il est "
            f"lancé (`ollama serve`). Détail : {exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise OllamaError(f"Réponse Ollama invalide : {exc}") from exc
    return (data.get("response") or "").strip()


def generate_description(
    project_name: str,
    context: str = "",
    *, model: str, host: str = DEFAULT_HOST, timeout: float = DEFAULT_TIMEOUT,
) -> str:
    """Génère une courte description (2-4 phrases, Markdown) pour un projet."""
    prompt = (
        "Tu es un assistant qui rédige des descriptions courtes et claires "
        "pour des projets logiciels. Réponds uniquement en français, en "
        "Markdown, en 2 à 4 phrases maximum, sans préambule ni titre.\n\n"
        f"Nom du projet : {project_name}\n"
    )
    if context.strip():
        prompt += f"Contexte disponible (README, fichiers...) :\n{context.strip()[:4000]}\n\n"
    prompt += "Rédige la description :"

    text = _generate(host, model, prompt, timeout)
    if not text:
        raise OllamaError("Ollama a renvoyé une réponse vide.")
    return text


_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]"
)


def suggest_emoji(
    project_name: str,
    context: str = "",
    *, model: str, host: str = DEFAULT_HOST, timeout: float = DEFAULT_TIMEOUT,
) -> str:
    """Suggère un unique emoji Unicode pertinent pour représenter le projet."""
    prompt = (
        "Réponds UNIQUEMENT avec un seul emoji Unicode qui représente le "
        "mieux le projet suivant, sans aucun texte ni explication autour.\n\n"
        f"Nom du projet : {project_name}\n"
    )
    if context.strip():
        prompt += f"Contexte : {context.strip()[:1000]}\n"
    prompt += "Emoji :"

    text = _generate(host, model, prompt, timeout)
    match = _EMOJI_RE.search(text)
    if not match:
        raise OllamaError(
            f"Ollama n'a pas renvoyé d'emoji reconnaissable (réponse reçue : {text!r})."
        )
    return match.group(0)
