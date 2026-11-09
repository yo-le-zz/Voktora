"""API de plugins v4 (1.1.0) : état des projets, recherche, modification confirmée, IA confirmée, événements de synchro."""

import core
import pytest
from plugins import manifest, runtime
from plugins.runtime import PluginAPI, PluginError, PluginInfo


class Host:
    def __init__(self, answer=True):
        self.answer, self.asked = answer, []

    def confirm(self, title, text):
        self.asked.append((title, text))
        return self.answer


def api_with(*perms):
    info = PluginInfo(name="Demo", version="1.0.0", author="a", path=runtime.plugins_dir() / "demo", id="demo",
                      permissions=list(perms))
    return PluginAPI(info)


@pytest.fixture
def host(isolated_data_dir):
    h = Host()
    runtime.set_ui_host(h)
    yield h
    runtime.set_ui_host(None)


def test_v4_declared():
    assert manifest.API_VERSION == 4
    for p in ("fleet", "projects.write", "ai"):
        assert p in manifest.PERMISSIONS
    assert "on_sync_start" in runtime.EVENTS and "on_sync_done" in runtime.EVENTS


def test_fleet_and_search_need_permission(host, tmp_path):
    with pytest.raises(PluginError):
        api_with().fleet_states()
    folder = tmp_path / "p"
    folder.mkdir()
    (folder / "a.txt").write_text("trouve-moi\n")
    core.register_project(folder, name="p")
    states = api_with("fleet").fleet_states()
    assert states[0]["name"] == "p" and "pas de dépôt Git" in states[0]["problems"]
    assert api_with("fleet").search_projects("trouve-moi")[0]["kind"] == "contenu"


def test_project_update_is_confirmed(host, tmp_path):
    folder = tmp_path / "p"
    folder.mkdir()
    core.register_project(folder, name="p")
    api = api_with("projects.write")
    host.answer = False
    assert api.project_update(folder, description="x") is False and not core.get_project(folder).get("description")
    host.answer = True
    assert api.project_update(folder, description="ok") is True and core.get_project(folder)["description"] == "ok"
    with pytest.raises(PluginError):
        api.project_update(folder, path="/etc")


def test_ai_ask_confirms_and_uses_active_provider(host, monkeypatch):
    import ai_providers
    cfg = core.get_ai_config()
    cfg["providers"] = [{"id": "p", "kind": "openai", "name": "R", "host": "http://localhost:1/v1", "model": "m", "api_key": ""}]
    cfg["active"] = "p"
    core.set_ai_config(cfg)
    monkeypatch.setattr(ai_providers, "generate", lambda prov, prompt, **k: "réponse:" + prompt)
    api = api_with("ai")
    assert api.ai_ask("salut") == "réponse:salut" and "salut" in host.asked[0][1]
    host.answer = False
    with pytest.raises(PluginError):
        api.ai_ask("non")
    with pytest.raises(PluginError):
        api_with().ai_ask("x")


def test_sync_events_reach_the_hook(tmp_path):
    from sync.service import SyncService
    svc = SyncService(tmp_path / "d", object(), {})
    seen = []
    svc.event_hook = lambda name, data: seen.append((name, data))
    svc._event("on_sync_done", peer="x", summary="s")
    svc.event_hook = lambda *_: 1 / 0                              # un plugin qui plante ne casse jamais la synchro
    svc._event("on_sync_done", peer="x")
    assert seen == [("on_sync_done", {"peer": "x", "summary": "s"})]
