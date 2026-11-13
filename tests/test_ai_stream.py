"""Chat IA 1.1.1 : vrai streaming (SSE / NDJSON), annulation, délai d'inactivité, Markdown, filtre des outils."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import ai_agent
import ai_providers
import markdown_lite
import pytest


class _H(BaseHTTPRequestHandler):
    mode = "sse"
    delay = 0.0

    def log_message(self, *a):
        pass

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n))
        assert body["stream"] is True
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream" if self.mode == "sse" else "application/x-ndjson")
        self.end_headers()
        pieces = ["Bon", "jour ", "**le** ", "monde"]
        for p in pieces:
            time.sleep(self.delay)
            if self.mode == "sse":
                chunk = {"choices": [{"delta": {"content": p}, "finish_reason": None}]}
                self.wfile.write(b"data: " + json.dumps(chunk).encode() + b"\n\n")
            else:
                self.wfile.write(json.dumps({"response": p, "done": False}).encode() + b"\n")
            self.wfile.flush()
        if self.mode == "sse":
            self.wfile.write(b"data: [DONE]\n\n")
        else:
            self.wfile.write(json.dumps({"response": "", "done": True}).encode() + b"\n")
        self.wfile.flush()


@pytest.fixture
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()


def _provider(srv, kind):
    host = f"http://127.0.0.1:{srv.server_address[1]}" + ("" if kind == "ollama" else "/v1")
    return {"kind": kind, "model": "m", "host": host, "name": "t"}


@pytest.mark.parametrize("kind,mode", [("openai", "sse"), ("ollama", "ndjson")])
def test_stream_tokens_arrive_one_by_one(server, kind, mode):
    _H.mode, _H.delay = mode, 0
    got = []
    text = ai_providers.generate(_provider(server, kind), "salut", on_token=got.append)
    assert got == ["Bon", "jour ", "**le** ", "monde"] and text == "Bonjour **le** monde"


def test_stream_cancel_returns_partial(server):
    _H.mode, _H.delay = "sse", 0.3
    stop = threading.Event()
    got = []

    def on_token(p):
        got.append(p)
        stop.set()                         # arrêt demandé dès le premier jeton

    start = time.time()
    text = ai_providers.generate(_provider(server, "openai"), "x", on_token=on_token, cancel=stop.is_set)
    assert text.startswith("Bon") and time.time() - start < 1.2 and len(got) < 4


def test_parse_stream_line_errors_and_noise():
    assert ai_providers.parse_stream_line("openai", ": keep-alive") == ("", False)
    assert ai_providers.parse_stream_line("openai", "data: [DONE]") == ("", True)
    with pytest.raises(ai_providers.AIError):
        ai_providers.parse_stream_line("ollama", json.dumps({"error": "modèle absent"}))


def test_idle_timeout_is_reported(server):
    _H.mode, _H.delay = "sse", 2.0
    with pytest.raises(ai_providers.AIError, match="rien envoyé"):
        ai_providers.generate(_provider(server, "openai"), "x", timeout=0.5, on_token=lambda p: None)


def test_visible_filter_hides_tool_blocks_and_think():
    out = []
    v = ai_agent._Visible(out.append)
    for piece in ["<think>réfl", "exion</think>Je ", "regarde.\\n`", "``tool\\n{\"name\":\"x\"}\\n```"]:
        v.feed(piece.replace("\\n", "\n"))
    v.finish()
    assert "".join(out) == "Je regarde.\n"


def test_visible_filter_releases_false_alarm():
    out = []
    v = ai_agent._Visible(out.append)
    v.feed("un `code`")
    v.finish()
    assert "".join(out) == "un `code`"


def test_markdown_basics_and_safety():
    h = markdown_lite.render("# Titre\n\n**gras** et *ital* `c<d>`\n\n- a\n- b\n\n1. x\n\n```py\nprint('<b>')\n```\n\n"
                             "| a | b |\n|---|---|\n| 1 | 2 |\n\n[ok](https://x.org) [mal](javascript:alert(1)) <script>x</script>")
    assert "<b>gras</b>" in h and "<i>ital</i>" in h and "<li>a</li>" in h and "<ol" in h
    assert "&lt;b&gt;" in h and "<th" in h and "href='https://x.org'" in h
    assert "javascript:" not in h.split("href='")[-1] if "href='javascript" in h else True
    assert "href='javascript" not in h and "<script>" not in h


def test_markdown_unclosed_fence_while_streaming():
    assert "<pre" in markdown_lite.render("```python\nx = 1")


def test_chat_dialog_streams_and_renders_markdown(isolated_data_dir):
    import core
    from PySide6.QtWidgets import QApplication
    from ui_dialogs import AIChatDialog
    app = QApplication.instance() or QApplication([])
    cfg = core.get_ai_config()
    cfg["providers"] = [{"id": "p1", "kind": "openai", "name": "T", "host": "http://localhost:1/v1", "model": "m", "api_key": ""}]
    cfg["active"] = "p1"
    core.set_ai_config(cfg)

    def fake(provider, prompt, on_token=None, **kw):
        for p in ["Voici ", "**gras**", "\n\n- un\n- deux"]:
            on_token(p)
        return "Voici **gras**\n\n- un\n- deux"

    dlg = AIChatDialog(generate=fake)
    dlg.edit.setPlainText("salut")
    dlg._send()
    for _ in range(100):
        app.processEvents()
        if not dlg._busy:
            break
        time.sleep(0.05)
    assert "**" not in dlg.view.toPlainText() and "gras" in dlg.view.toPlainText()
    assert "Voici" in dlg.view.toPlainText()
