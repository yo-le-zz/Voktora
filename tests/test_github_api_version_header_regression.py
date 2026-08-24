"""
Régression : lors du découpage de core.py en package, un script de
qualification automatique des références inter-modules avait par erreur
transformé le header HTTP littéral "X-GitHub-Api-Version" en
"X-GitHub-Api-constants.Version" (le mot "Version" précédé d'un tiret
n'était pas protégé par la regex de qualification). Toute requête vers
l'API GitHub App envoyait alors un nom de header invalide.
"""

import core


class TestGithubApiVersionHeader:
    def test_installation_token_request_uses_correct_header_name(self, isolated_data_dir, monkeypatch):
        captured = {}

        class _FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                import json
                return json.dumps({"token": "ghs_fake", "expires_at": "2099-01-01T00:00:00Z"}).encode()

        def fake_urlopen(req, timeout=None):
            captured["headers"] = dict(req.header_items())
            return _FakeResponse()

        monkeypatch.setattr(core.github_auth.urllib.request, "urlopen", fake_urlopen)
        monkeypatch.setattr(
            core.github_auth, "_build_jwt", lambda app_id, key: "fake.jwt.token"
        )

        core.github_auth._get_installation_token_cached("123", "fake-key", "456")

        header_names = list(captured["headers"].keys())
        assert any(h.lower() == "x-github-api-version" for h in header_names)
        assert not any("constants" in h.lower() for h in header_names)
