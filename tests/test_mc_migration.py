import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "voktora"))

import core
import mc


def _seed_instances(n=2):
    cfg = core._load_config()
    cfg["instances"] = [
        {"name": f"proj{i}", "path": f"D:\\Projects\\proj{i}", "status": "actif"}
        for i in range(n)
    ]
    cfg["intents"] = [{"name": "idée1", "path": "D:\\Projects\\idea1"}]
    core._save_config(cfg)


class TestExportBundle:
    def test_export_creates_valid_bundle(self, isolated_data_dir, tmp_path):
        _seed_instances(2)
        dest = tmp_path / "out.mpack"
        res = mc.export_bundle(dest)
        assert res.success is True
        assert dest.exists()

    def test_export_excludes_secrets(self, isolated_data_dir, tmp_path):
        core.save_github_account(token="ghp_secret_token", user_info={"login": "octocat"})
        dest = tmp_path / "out.mpack"
        mc.export_bundle(dest)

        import zipfile
        with zipfile.ZipFile(dest) as zf:
            raw = zf.read("config.json").decode("utf-8")
        assert "ghp_secret_token" not in raw
        assert "github_account" not in raw


class TestValidateBundle:
    def test_missing_file(self, tmp_path):
        info = mc.validate_bundle(tmp_path / "nope.mpack")
        assert info["valid"] is False

    def test_not_a_zip(self, tmp_path):
        p = tmp_path / "fake.mpack"
        p.write_text("not a zip")
        info = mc.validate_bundle(p)
        assert info["valid"] is False

    def test_valid_bundle_reports_project_count(self, isolated_data_dir, tmp_path):
        _seed_instances(3)
        dest = tmp_path / "out.mpack"
        mc.export_bundle(dest)
        info = mc.validate_bundle(dest)
        assert info["valid"] is True
        assert info["manifest"]["_detected_project_count"] == 4  # 3 instances + 1 intent


class TestImportBundle:
    def test_import_rewrites_paths_with_matching_rule(self, isolated_data_dir, tmp_path):
        _seed_instances(1)
        bundle = tmp_path / "out.mpack"
        mc.export_bundle(bundle)

        # Repartir d'une config vide pour simuler une autre machine.
        core._config_cache = None
        core.get_config_path().unlink()

        res = mc.import_bundle(
            bundle, base=tmp_path / "fallback",
            custom_rules=[("D:\\Projects", "/home/user/Projects")],
        )
        assert res.success is True
        cfg = core._load_config()
        assert cfg["instances"][0]["path"] == "/home/user/Projects\\proj0"

    def test_import_falls_back_to_base_when_no_rule_matches(self, isolated_data_dir, tmp_path):
        _seed_instances(1)
        bundle = tmp_path / "out.mpack"
        mc.export_bundle(bundle)
        core._config_cache = None
        core.get_config_path().unlink()

        fallback = tmp_path / "fallback"
        res = mc.import_bundle(bundle, base=fallback, custom_rules=[])
        assert res.success is True
        cfg = core._load_config()
        assert cfg["instances"][0]["path"] == str(fallback / "proj0")

    def test_import_invalid_bundle_fails_cleanly(self, isolated_data_dir, tmp_path):
        bad = tmp_path / "bad.mpack"
        bad.write_text("garbage")
        res = mc.import_bundle(bad, base=tmp_path, custom_rules=[])
        assert res.success is False
