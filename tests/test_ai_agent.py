"""Chat IA agent (1.1.0) : outils filtrés par permissions, confirmations, secrets jamais exposés."""

import json
from pathlib import Path

import ai_agent
import core
import pytest


def _tool(_n, **args):
    return "```tool\n" + json.dumps({"name": _n, "args": args}) + "\n```"


class Script:
    """Faux fournisseur : renvoie les réponses prévues dans l'ordre et garde les invites reçues."""

    def __init__(self, *answers):
        self.answers, self.prompts = list(answers), []

    def __call__(self, provider, prompt, **kw):
        self.prompts.append(prompt)
        return self.answers.pop(0)


@pytest.fixture
def project(isolated_data_dir, tmp_path):
    path = tmp_path / "demo"
    path.mkdir()
    core.register_project(path, name="demo", category="Perso")
    return path


def make(script, confirm=lambda t, d: True, events=None):
    return ai_agent.Agent({"kind": "openai", "model": "m"}, confirm,
                          (lambda k, t: events.append((k, t))) if events is not None else None, generate=script)


def test_parse_tool_call_variants():
    assert ai_agent.parse_tool_call(_tool("list_projects")) == {"name": "list_projects", "args": {}}
    assert ai_agent.parse_tool_call('<tool_call>{"name":"x","arguments":{"a":1}}</tool_call>') == {"name": "x", "args": {"a": 1}}
    assert ai_agent.parse_tool_call("pas d'outil") is None
    assert ai_agent.parse_tool_call("```tool\n{pas json}\n```") is None


def test_agent_lists_projects_then_answers(project):
    script = Script(_tool("list_projects"), "Vous avez 1 projet : demo.")
    agent = make(script)
    assert agent.ask("liste mes projets") == "Vous avez 1 projet : demo."
    assert "demo" in script.prompts[1] and "Résultat d'outil" in script.prompts[1]


def test_disabled_permission_hides_and_blocks_tool(project):
    ai_agent.set_permission("projects.list", "off")
    script = Script(_tool("list_projects"), "ok")
    agent = make(script)
    agent.ask("liste")
    assert "list_projects —" not in script.prompts[0]              # même pas présenté au modèle
    assert "ERREUR" in agent.history[1].text + agent.history[2].text or "n'est pas disponible" in agent.history[2].text


def test_write_tools_always_confirm_even_if_auto(project):
    assert ai_agent.set_permission("projects.write", "auto") == "ask"
    asked = []
    script = Script(_tool("update_project", name="demo", fields={"description": "salut"}), "fait")
    agent = make(script, confirm=lambda t, d: asked.append((t, d)) or True)
    agent.ask("décris demo")
    assert asked and "demo" in asked[0][1]
    assert core.get_project(project)["description"] == "salut"


def test_refused_action_is_not_executed(project):
    script = Script(_tool("update_project", name="demo", fields={"description": "NON"}), "d'accord")
    agent = make(script, confirm=lambda t, d: False)
    agent.ask("modifie")
    assert not core.get_project(project).get("description")
    assert "REFUSÉ" in agent.history[2].text


def test_read_auto_needs_no_confirmation(project):
    asked = []
    script = Script(_tool("get_project", name="demo"), "ok")
    make(script, confirm=lambda t, d: asked.append(1) or True).ask("infos")
    assert not asked


def test_secrets_never_reach_the_model(project):
    cfg = core._load_config()
    cfg["app_config"]["github_token"] = "ghp_SECRET"
    cfg["app_config"]["theme"] = "dark"
    core._save_config(cfg)
    agent = make(Script("x"))
    shown = agent.call_tool("get_setting", {})
    assert "ghp_SECRET" not in shown and "theme" in shown
    assert "protégé" in agent.call_tool("get_setting", {"key": "github_token"})
    assert "protégé" in agent.call_tool("set_setting", {"key": "github_token", "value": "x"})
    assert "protégé" in agent.call_tool("set_setting", {"key": "ai", "value": {}})
    assert "ghp_SECRET" not in json.dumps(ai_agent._clean({"a": {"api_key": "k", "ok": 1}, "tok": 1}))


def test_unknown_field_and_project_errors_are_explained(project):
    agent = make(Script("x"))
    assert "non modifiables" in agent.call_tool("update_project", {"name": "demo", "fields": {"path": "/etc"}})
    assert "introuvable" in agent.call_tool("get_project", {"name": "nope"})


def test_run_command_no_shell_and_confirmed(project):
    asked = []
    agent = make(Script("x"), confirm=lambda t, d: asked.append(d) or True)
    out = agent.call_tool("run_command", {"command": "echo salut; echo injection", "project": "demo"})
    assert asked and "salut; echo injection" in out        # pas d'interpréteur : le « ; » reste un argument
    assert json.loads(out)["exit_code"] == 0


def test_loop_is_bounded(project):
    script = Script(*[_tool("list_projects")] * 20)
    agent = make(script)
    assert "Trop d'étapes" in agent.ask("boucle")
    assert len(script.prompts) == ai_agent.MAX_STEPS + 1


def test_history_is_bounded(project):
    agent = make(Script("ok"))
    agent.history = [ai_agent.ChatMessage("user", "x" * 5000) for _ in range(10)]
    assert len(ai_agent._history_text(agent.history)) < ai_agent.HISTORY_LIMIT + 6000


def test_permission_levels_persist_and_validate(isolated_data_dir):
    assert ai_agent.set_permission("sync.run", "off") == "off"
    assert ai_agent.permission_levels()["sync.run"] == "off"
    with pytest.raises(ValueError):
        ai_agent.set_permission("nope", "ask")
    assert Path  # noqa


def test_chat_dialog_roundtrip_with_confirmation(project, monkeypatch):
    from PySide6.QtWidgets import QApplication, QMessageBox
    from ui_dialogs import AIChatDialog
    app = QApplication.instance() or QApplication([])
    cfg = core.get_ai_config()
    cfg["providers"] = [{"id": "p1", "kind": "openai", "name": "Test", "host": "http://localhost:1/v1", "model": "m", "api_key": ""}]
    cfg["active"] = "p1"
    core.set_ai_config(cfg)
    script = Script(_tool("update_project", name="demo", fields={"description": "via chat"}), "Description mise à jour.")
    dlg = AIChatDialog(generate=script)
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.Yes)
    dlg.edit.setPlainText("décris demo")
    dlg._send()
    import time
    for _ in range(100):
        app.processEvents()
        if not dlg._busy:
            break
        time.sleep(0.05)
    assert "Description mise à jour." in dlg.view.toPlainText()
    assert core.get_project(project)["description"] == "via chat"


def test_search_and_fleet_tools(project):
    (project / "n.txt").write_text("aiguille dans la botte\n")
    agent = make(Script("x"))
    assert "aiguille" in agent.call_tool("search_projects", {"query": "aiguille"})
    assert "pas de dépôt Git" in agent.call_tool("fleet_status", {})
    ai_agent.set_permission("projects.read", "off")
    assert "n'est pas disponible" in agent.call_tool("fleet_status", {})
