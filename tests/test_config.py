

def test_config_backed_up_when_version_changes(isolated_data_dir):
    import json

    import core
    cfg = core._load_config()
    cfg["_app_version"] = "1.0.9"            # version précédente
    core._save_config(cfg)
    core.invalidate_cache()
    core._load_config()
    backup = core.get_data_dir() / "config.backup-1.0.9.json"
    assert backup.exists() and json.loads(backup.read_text())["_app_version"] == "1.0.9"
    assert core._load_config()["_app_version"] == core.APP_VERSION
