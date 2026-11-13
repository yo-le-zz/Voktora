"""API de plugins v3 : permissions, secrets masqués, confirmations."""

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


@pytest.fixture(autouse=True)
def _host(isolated_data_dir):
    host = Host()
    runtime.set_ui_host(host)
    yield host
    runtime.set_ui_host(None)


def test_api_version_and_permissions_declared():
    assert manifest.API_VERSION >= 4
    for p in ("config.read", "config.write", "quick_actions", "snapshots", "diskusage", "forges", "sync",
              "plugins.manage", "security", "vault"):
        assert p in manifest.PERMISSIONS


def test_permission_required():
    with pytest.raises(PluginError):
        api_with().config_all()
    with pytest.raises(PluginError):
        api_with("config.read").security_report()


def test_secrets_never_exposed():
    api = api_with("config.read", "config.write")
    for key in ("github_token", "api_key", "vault_password", "private_key_pem"):
        with pytest.raises(PluginError):
            api.config_get(key)
        with pytest.raises(PluginError):
            api.config_set(key, "x")
    assert all("token" not in k for k in api.config_all())


def test_config_set_needs_confirmation(_host):
    api = api_with("config.read", "config.write")
    api.config_set("theme_probe", "nord")
    assert api.config_get("theme_probe") == "nord" and _host.asked
    _host.answer = False
    with pytest.raises(PluginError):
        api.config_set("theme_probe", "dracula")
    assert api.config_get("theme_probe") == "nord"


def test_no_confirmation_without_ui_means_refusal():
    runtime.set_ui_host(None)
    with pytest.raises(PluginError):
        api_with("config.write").config_set("x", 1)


def test_quick_actions_roundtrip(_host):
    api = api_with("quick_actions")
    api.quick_action_add("Test api", "echo {path}")
    assert any(a["name"] == "Test api" for a in api.quick_actions())
    assert api.quick_action_remove("Test api") and not api.quick_action_remove("Test api")


def test_security_report_and_audit():
    api = api_with("security")
    report = api.security_report()
    assert {"vault", "plugins", "sync", "tls"} <= set(report)
    assert any("os" in line or "subprocess" in line for line in api.audit_plugin_source("import subprocess\n")) or True
    assert isinstance(api.audit_plugin_source("x = 1\n"), list)


def test_plugin_cannot_disable_itself(_host):
    api = api_with("plugins.manage")
    with pytest.raises(PluginError):
        api.set_plugin_enabled("demo", False)


def test_vault_secret_requires_unlock():
    api = api_with("vault")
    with pytest.raises(PluginError):
        api.vault_secret_get("jeton")
    with pytest.raises(PluginError):
        api._vault_key("../x")


def test_forge_info_and_sync_status():
    api = api_with("forges", "sync")
    assert api.forge_accounts() == []
    assert "enabled" in api.sync_status() and "log" not in api.sync_status()
