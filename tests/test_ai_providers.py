"""Fournisseurs d'IA : OmniRoute / compatible OpenAI (serveur factice local) et Ollama."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar

import ai_providers as ai
import pytest


class _Handler(BaseHTTPRequestHandler):
    seen: ClassVar[list] = []
    reply = "Une <think>réflexion</think>description."

    def log_message(self, *args):  # silence
        pass

    def _send(self, code, body):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        _Handler.seen.append((self.path, self.headers.get("Authorization")))
        if self.path == "/v1/models":
            self._send(200, {"data": [{"id": "gpt-b"}, {"id": "auto"}]})
        elif self.path == "/api/tags":
            self._send(200, {"models": [{"name": "llama3"}]})
        else:
            self._send(404, {"error": "nope"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _Handler.seen.append((self.path, self.headers.get("Authorization"), body))
        if self.path == "/v1/chat/completions":
            self._send(200, {"choices": [{"message": {"content": _Handler.reply}}]})
        elif self.path == "/api/generate":
            self._send(200, {"response": "ollama dit bonjour"})
        else:
            self._send(404, {})


@pytest.fixture
def server():
    _Handler.seen = []
    _Handler.reply = "Une <think>réflexion</think>description."
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def _omni(host, **extra):
    return {"id": "o", "kind": "omniroute", "name": "OmniRoute", "host": host, "model": "auto",
            "api_key": "sk-test", **extra}


def test_normalize_host_adds_v1_for_openai_like_only():
    assert ai.normalize_host("omniroute", "localhost:20128") == "http://localhost:20128/v1"
    assert ai.normalize_host("openai", "https://api.x.org/") == "https://api.x.org/v1"
    assert ai.normalize_host("omniroute", "http://h:1/custom/v1/") == "http://h:1/custom/v1"
    assert ai.normalize_host("ollama", "http://h:11434/") == "http://h:11434"
    assert ai.normalize_host("omniroute", "") == "http://localhost:20128/v1"


@pytest.mark.parametrize("bad", ["file:///etc/passwd", "ftp://x/y", "javascript:alert(1)"])
def test_non_http_schemes_are_rejected(bad):
    with pytest.raises(ai.AIError):
        ai.normalize_host("openai", bad)


def test_list_models_sends_bearer_key(server):
    assert ai.list_models(_omni(server)) == ["auto", "gpt-b"]
    assert _Handler.seen[0] == ("/v1/models", "Bearer sk-test")


def test_generate_description_uses_chat_completions_and_strips_think(server):
    text = ai.generate_description(_omni(server), "Voktora", "readme")
    assert text == "Une description."
    path, auth, body = _Handler.seen[-1]
    assert path == "/v1/chat/completions" and auth == "Bearer sk-test"
    assert body["model"] == "auto" and body["stream"] is False and "Voktora" in body["messages"][0]["content"]


def test_ollama_provider_uses_native_api(server):
    provider = {"id": "ollama", "kind": "ollama", "name": "Ollama", "host": server, "model": "llama3", "api_key": ""}
    assert ai.list_models(provider) == ["llama3"]
    assert ai.generate(provider, "salut") == "ollama dit bonjour"


def test_api_key_is_refused_over_plain_http_to_a_public_host():
    provider = _omni("http://api.example.com/v1")
    with pytest.raises(ai.AIError, match="https"):
        ai.list_models(provider)


def test_private_hosts_are_recognised():
    assert all(ai._is_private_host(h) for h in ("localhost", "127.0.0.1", "192.168.1.4", "10.0.0.2", "omni", "box.local"))
    assert not any(ai._is_private_host(h) for h in ("api.openai.com", "8.8.8.8"))


def test_missing_model_and_unknown_route_give_clear_errors(server):
    with pytest.raises(ai.AIError, match="modèle"):
        ai.generate({**_omni(server), "model": ""}, "x")
    with pytest.raises(ai.AIError, match="introuvable"):
        ai._request(_omni(server), "GET", "/inconnu", None, 5)


def test_unreachable_server_error_never_leaks_the_key():
    with pytest.raises(ai.AIError) as info:
        ai.list_models(_omni("http://127.0.0.1:9"))
    assert "sk-test" not in str(info.value)


def test_suggest_icon_picks_first_known_id_and_rejects_unknown(server):
    choices = ["mdi:rocket-launch", "mdi:bug", "mdi:lock"]
    _Handler.reply = "Je dirais mdi:bug (ou mdi:lock)."
    assert ai.suggest_icon(_omni(server), "App", choices) == "mdi:bug"
    _Handler.reply = "aucune idée"
    with pytest.raises(ai.AIError):
        ai.suggest_icon(_omni(server), "App", choices)
    assert ai.pick_icon_id("mdi:bug-report", choices) is None      # pas de correspondance partielle


def test_project_digest_drops_noise_and_is_bounded():
    readme = (
        "# Atlantis\n[![CI](https://x/badge.svg)](https://x)\n![logo](a.png)\n\n"
        "Un outil pour **gérer** des fichiers.\n\n```bash\npip install atlantis\n```\n"
        "| a | b |\n|---|---|\nVoir [la doc](https://docs).\n" + ("Ligne utile. " * 200)
    )
    digest = ai.project_digest(readme, "notes", ["main.py", "README.md"])
    assert "badge" not in digest and "pip install" not in digest and "a.png" not in digest
    assert "Atlantis" in digest and "la doc" in digest and "https" not in digest
    assert len(digest) <= ai.DIGEST_MAX_CHARS


def test_shortlist_prefers_relevant_icons_and_is_bounded():
    choices = [f"mdi:thing-{i}" for i in range(80)] + ["mdi:bug", "mdi:web", "mdi:database"]
    short = ai.shortlist_icons(choices, "mon site web", keywords={"mdi:web": "site internet web"}, limit=5)
    assert len(short) == 5 and short[0] == "mdi:web"
    assert ai.shortlist_icons(["mdi:a"], "rien", limit=12) == ["mdi:a"]


def test_suggest_icon_only_sends_a_shortlist(monkeypatch):
    sent = {}

    def fake_generate(provider, prompt, timeout=0, max_tokens=None):
        sent["prompt"], sent["max"] = prompt, max_tokens
        return "mdi:web"

    monkeypatch.setattr(ai, "generate", fake_generate)
    choices = [f"mdi:x{i}" for i in range(300)] + ["mdi:web"]
    assert ai.suggest_icon({"model": "m"}, "Site web", choices, keywords={"mdi:web": "web site"}) == "mdi:web"
    assert sent["prompt"].count("mdi:") <= ai.ICON_SHORTLIST + 2
    assert sent["max"] == ai.ICON_MAX_TOKENS
