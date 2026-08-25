import json
import urllib.error

import ollama_client as oc


class _FakeResponse:
    def __init__(self, payload: dict, status: int = 200):
        self._payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


class TestIsAvailable:
    def test_true_when_server_responds_200(self, monkeypatch):
        monkeypatch.setattr(
            oc.urllib.request, "urlopen",
            lambda req, timeout=None: _FakeResponse({}, status=200)
        )
        assert oc.is_available() is True

    def test_false_when_connection_fails(self, monkeypatch):
        def raise_it(req, timeout=None):
            raise urllib.error.URLError("connection refused")
        monkeypatch.setattr(oc.urllib.request, "urlopen", raise_it)
        assert oc.is_available() is False


class TestListModels:
    def test_parses_model_names(self, monkeypatch):
        monkeypatch.setattr(
            oc.urllib.request, "urlopen",
            lambda req, timeout=None: _FakeResponse(
                {"models": [{"name": "llama3.1:8b"}, {"name": "mistral:latest"}]}
            )
        )
        assert oc.list_models() == ["llama3.1:8b", "mistral:latest"]

    def test_raises_ollama_error_when_unreachable(self, monkeypatch):
        def raise_it(req, timeout=None):
            raise urllib.error.URLError("connection refused")
        monkeypatch.setattr(oc.urllib.request, "urlopen", raise_it)
        try:
            oc.list_models()
            raise AssertionError("aurait dû lever OllamaError")
        except oc.OllamaError:
            pass


class TestGenerateDescription:
    def test_returns_response_text(self, monkeypatch):
        monkeypatch.setattr(
            oc.urllib.request, "urlopen",
            lambda req, timeout=None: _FakeResponse({"response": "Un outil de gestion de projets."})
        )
        result = oc.generate_description("Voktora", model="llama3.1")
        assert result == "Un outil de gestion de projets."

    def test_raises_on_empty_response(self, monkeypatch):
        monkeypatch.setattr(
            oc.urllib.request, "urlopen",
            lambda req, timeout=None: _FakeResponse({"response": "   "})
        )
        try:
            oc.generate_description("Voktora", model="llama3.1")
            raise AssertionError("aurait dû lever OllamaError")
        except oc.OllamaError:
            pass

    def test_raises_without_model(self, monkeypatch):
        try:
            oc.generate_description("Voktora", model="")
            raise AssertionError("aurait dû lever OllamaError")
        except oc.OllamaError:
            pass

    def test_includes_context_in_prompt(self, monkeypatch):
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return _FakeResponse({"response": "ok"})

        monkeypatch.setattr(oc.urllib.request, "urlopen", fake_urlopen)
        oc.generate_description("Voktora", context="Gestionnaire de projets Qt", model="llama3.1")
        assert "Gestionnaire de projets Qt" in captured["body"]["prompt"]
        assert captured["body"]["stream"] is False
        assert captured["body"]["model"] == "llama3.1"


class TestSuggestEmoji:
    def test_extracts_emoji_from_response(self, monkeypatch):
        monkeypatch.setattr(
            oc.urllib.request, "urlopen",
            lambda req, timeout=None: _FakeResponse({"response": "🚀"})
        )
        assert oc.suggest_emoji("Voktora", model="llama3.1") == "🚀"

    def test_extracts_emoji_even_with_surrounding_text(self, monkeypatch):
        # Certains modèles ignorent la consigne "uniquement l'emoji" ;
        # on doit pouvoir en extraire un malgré tout.
        monkeypatch.setattr(
            oc.urllib.request, "urlopen",
            lambda req, timeout=None: _FakeResponse({"response": "Voici l'emoji : 🎯 j'espère que ça convient !"})
        )
        assert oc.suggest_emoji("Voktora", model="llama3.1") == "🎯"

    def test_raises_when_no_emoji_in_response(self, monkeypatch):
        monkeypatch.setattr(
            oc.urllib.request, "urlopen",
            lambda req, timeout=None: _FakeResponse({"response": "Je ne sais pas."})
        )
        try:
            oc.suggest_emoji("Voktora", model="llama3.1")
            raise AssertionError("aurait dû lever OllamaError")
        except oc.OllamaError:
            pass

    def test_http_error_is_wrapped(self, monkeypatch):
        def raise_it(req, timeout=None):
            raise urllib.error.HTTPError("url", 500, "Internal Server Error", {}, None)
        monkeypatch.setattr(oc.urllib.request, "urlopen", raise_it)
        try:
            oc.suggest_emoji("Voktora", model="llama3.1")
            raise AssertionError("aurait dû lever OllamaError")
        except oc.OllamaError:
            pass
