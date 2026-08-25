import json

import core
import pytest


class TestConfigMigration:
    def test_fresh_config_has_all_required_keys(self, isolated_data_dir):
        cfg = core._load_config()
        assert cfg["_schema_version"] == core.CONFIG_SCHEMA_VERSION
        for key in ("instances", "intents", "storage", "github_account",
                    "categories", "custom_statuses", "app_config", "vault"):
            assert key in cfg

    def test_old_schema_is_migrated_to_current_version(self, isolated_data_dir):
        core.get_config_path().write_text(json.dumps({
            "_schema_version": 1,
            "instances": [{"path": "/tmp/proj", "name": "proj"}],
        }), encoding="utf-8")
        core._config_cache = None

        cfg = core._load_config()
        assert cfg["_schema_version"] == core.CONFIG_SCHEMA_VERSION
        entry = cfg["instances"][0]
        assert entry["status"] == core.DEFAULT_PROJECT_STATUS
        assert "github_branches" in entry
        assert cfg["app_config"]["auth_method"] == core.AUTH_METHOD_OAUTH

    def test_migration_is_idempotent(self, isolated_data_dir):
        cfg = core._load_config()
        core._config_cache = None
        cfg_again = core._load_config()
        assert cfg == cfg_again

    def test_corrupted_config_raises(self, isolated_data_dir):
        core.get_config_path().write_text("{not valid json", encoding="utf-8")
        core._config_cache = None
        try:
            core._load_config()
            pytest.fail("aurait dû lever ConfigCorruptedError")
        except core.ConfigCorruptedError:
            pass
