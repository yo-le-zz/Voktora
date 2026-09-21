import json

import core
import pytest


def _write_config(data: dict) -> None:
    core.get_config_path().write_text(json.dumps(data), encoding="utf-8")
    core.invalidate_cache()


class TestConfigMigration:
    def test_fresh_config_has_all_required_keys(self, isolated_data_dir):
        cfg = core._load_config()
        assert cfg["_schema_version"] == core.CONFIG_SCHEMA_VERSION
        for key in ("projects", "storage", "github_account",
                    "categories", "custom_statuses", "app_config", "vault"):
            assert key in cfg
        assert "instances" not in cfg and "intents" not in cfg

    def test_old_schema_is_migrated_to_current_version(self, isolated_data_dir):
        _write_config({
            "_schema_version": 1,
            "instances": [{"path": "/tmp/proj", "name": "proj"}],
        })
        cfg = core._load_config()
        assert cfg["_schema_version"] == core.CONFIG_SCHEMA_VERSION
        entry = cfg["projects"][0]
        assert entry["status"] == core.DEFAULT_PROJECT_STATUS
        assert "github_branches" in entry
        assert cfg["app_config"]["auth_method"] == core.AUTH_METHOD_OAUTH

    def test_migration_is_idempotent(self, isolated_data_dir):
        cfg = core._load_config()
        core.invalidate_cache()
        cfg_again = core._load_config()
        assert cfg == cfg_again

    def test_corrupted_config_raises(self, isolated_data_dir):
        core.get_config_path().write_text("{not valid json", encoding="utf-8")
        core.invalidate_cache()
        with pytest.raises(core.ConfigCorruptedError):
            core._load_config()


class TestProjectsMigration:
    """Schéma 9 : instances + intents → projects."""

    def test_instances_and_intents_are_merged_in_order(self, isolated_data_dir):
        _write_config({
            "_schema_version": 8,
            "instances": [{"name": "a", "path": "/p/a", "github_repo": "https://github.com/o/a"}],
            "intents": [{"name": "b", "path": "/p/b"}],
        })
        cfg = core._load_config()
        assert [e["path"] for e in cfg["projects"]] == ["/p/a", "/p/b"]
        assert cfg["projects"][0]["github_repo"] == "https://github.com/o/a"
        assert "instances" not in cfg and "intents" not in cfg

    def test_duplicate_path_keeps_the_instance(self, isolated_data_dir):
        _write_config({
            "_schema_version": 8,
            "instances": [{"name": "inst", "path": "/p/x", "note": "garde-moi"}],
            "intents": [{"name": "idee", "path": "/p/x"}],
        })
        projects = core._load_config()["projects"]
        assert len(projects) == 1 and projects[0]["note"] == "garde-moi"

    def test_entries_get_all_default_fields(self, isolated_data_dir):
        _write_config({"_schema_version": 8, "intents": [{"name": "b", "path": "/p/b"}]})
        entry = core._load_config()["projects"][0]
        for key in ("note", "status", "category", "tags", "github_repo", "github_branch",
                    "github_branches", "github_token", "github_token_protected"):
            assert key in entry
        assert entry["tags"] == []

    def test_backup_of_previous_config_is_written_once(self, isolated_data_dir):
        _write_config({"_schema_version": 8, "instances": [{"name": "a", "path": "/p/a"}]})
        core._load_config()
        backup = core.get_config_path().with_name("config.pre-v9.json")
        assert backup.exists()
        assert json.loads(backup.read_text(encoding="utf-8"))["instances"][0]["name"] == "a"

    def test_storage_roots_are_unified(self, isolated_data_dir):
        _write_config({"_schema_version": 8,
                       "storage": {"instances_root": "/data/inst", "intents_root": "/data/int"}})
        assert core._load_config()["storage"] == {"projects_root": "/data/inst"}

    def test_storage_falls_back_to_intents_root(self, isolated_data_dir):
        _write_config({"_schema_version": 8, "storage": {"instances_root": None, "intents_root": "/data/int"}})
        assert core._load_config()["storage"]["projects_root"] == "/data/int"

    def test_string_categories_become_objects_and_used_ones_are_kept(self, isolated_data_dir):
        _write_config({
            "_schema_version": 8,
            "categories": ["Web", "web", "  "],
            "instances": [{"name": "a", "path": "/p/a", "category": "Jeux"}],
        })
        cats = core._load_config()["categories"]
        assert [c["name"] for c in cats] == ["Web", "Jeux"]
        assert set(cats[0]) == {"name", "emoji", "color"}

    def test_migration_survives_reload(self, isolated_data_dir):
        _write_config({"_schema_version": 8, "instances": [{"name": "a", "path": "/p/a"}]})
        first = core._load_config()
        core.invalidate_cache()
        assert core._load_config() == first


class TestLegacyFiles:
    def test_recognised_legacy_file_is_absorbed_then_removed(self, isolated_data_dir):
        legacy = core.get_config_path().parent / "instances.json"
        legacy.write_text(json.dumps({"instances": [{"name": "old", "path": "/p/old"}]}), encoding="utf-8")
        cfg = core._load_config()
        assert [e["name"] for e in cfg["projects"]] == ["old"]
        assert not legacy.exists()
        assert legacy.with_suffix(".json.legacy").exists()

    def test_unrelated_settings_json_is_left_alone(self, isolated_data_dir):
        # Régression : un « settings.json » d'un autre programme était absorbé puis supprimé.
        other = core.get_config_path().parent / "settings.json"
        other.write_text(json.dumps({"theme": "dark", "font": 12}), encoding="utf-8")
        core._load_config()
        assert other.exists()
        assert json.loads(other.read_text(encoding="utf-8")) == {"theme": "dark", "font": 12}

    def test_legacy_with_existing_config_does_not_recurse(self, isolated_data_dir):
        _write_config({"_schema_version": 9, "projects": [{"name": "cur", "path": "/p/cur"}]})
        legacy = core.get_config_path().parent / "voktora_config.json"
        legacy.write_text(json.dumps({"intents": [{"name": "old", "path": "/p/old"}]}), encoding="utf-8")
        cfg = core._load_config()
        assert {e["name"] for e in cfg["projects"]} == {"cur", "old"}
        assert core.show_migration_summary()
