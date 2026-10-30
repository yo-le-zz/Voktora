"""Export complet : phases séparées, isolation des échecs, aucun secret dans l'archive."""

import json
import zipfile

import core
import pytest
from core import archive, full_export


def _cfg(*folders):
    return {"projects": [{"name": f.name, "path": str(f), "github_token": "ghp_SECRET"} for f in folders],
            "github_account": {"token": "ghp_ACCOUNT"}, "vault": {"verifier": "v", "salt": "s"}, "categories": []}


@pytest.fixture
def two_projects(tmp_path):
    a, b = tmp_path / "a" / "same", tmp_path / "b" / "same"
    for folder, text in ((a, "A"), (b, "B")):
        folder.mkdir(parents=True)
        (folder / "f.txt").write_text(text)
    return a, b


class TestPlan:
    def test_duplicate_names_get_distinct_prefixes_and_missing_are_reported(self, two_projects, tmp_path):
        cfg = _cfg(*two_projects)
        cfg["projects"].append({"name": "ghost", "path": str(tmp_path / "ghost")})
        plan = full_export.plan_full_export(cfg)
        assert [s.archive_prefix for s in plan.sources] == ["projects/same", "projects/same_2"]
        assert plan.missing == ("ghost",)
        assert plan.total_bytes == 2

    def test_planning_writes_nothing(self, two_projects, tmp_path):
        before = sorted(p.name for p in tmp_path.rglob("*"))
        full_export.plan_full_export(_cfg(*two_projects))
        assert sorted(p.name for p in tmp_path.rglob("*")) == before


class TestWrite:
    def test_archive_has_projects_config_without_secrets_and_info(self, two_projects, tmp_path):
        cfg = _cfg(*two_projects)
        report = full_export.write_full_export(full_export.plan_full_export(cfg), cfg, tmp_path / "out")
        with zipfile.ZipFile(report.archive_path) as zf:
            assert zf.read("projects/same/f.txt") == b"A" and zf.read("projects/same_2/f.txt") == b"B"
            exported = json.loads(zf.read("config.json"))
            assert "github_account" not in exported and "vault" not in exported
            assert all(p["github_token"] == "" for p in exported["projects"])
            assert b"SECRET" not in b"".join(zf.read(n) for n in zf.namelist())
            assert "same" in zf.read("export_info.txt").decode()
        assert report.exported == ["same", "same"] and not report.has_warnings

    def test_one_failing_project_does_not_abort_the_others(self, two_projects, tmp_path, monkeypatch):
        cfg = _cfg(*two_projects)
        real = archive.add_tree_to_zip

        def flaky(zf, folder, prefix, tracker, cancel=None):
            if prefix.endswith("same"):
                raise RuntimeError("disque en feu")
            return real(zf, folder, prefix, tracker, cancel)

        monkeypatch.setattr(archive, "add_tree_to_zip", flaky)
        report = full_export.write_full_export(full_export.plan_full_export(cfg), cfg, tmp_path / "out")
        assert report.failed == [("same", "disque en feu")] and report.has_warnings
        with zipfile.ZipFile(report.archive_path) as zf:
            assert "projects/same_2/f.txt" in zf.namelist()
            assert "disque en feu" in zf.read("export_info.txt").decode()

    def test_cancel_aborts_and_leaves_no_archive(self, two_projects, tmp_path):
        cfg = _cfg(*two_projects)
        with pytest.raises(core.OperationCancelled):
            full_export.write_full_export(full_export.plan_full_export(cfg), cfg, tmp_path / "out", cancel=lambda: True)
        assert list((tmp_path / "out").glob("*")) == []

    def test_export_all_to_zip_keeps_its_string_contract(self, isolated_data_dir, two_projects):
        core.register_project(two_projects[0], str(two_projects[0].parent))
        result = core.export_all_to_zip()
        assert isinstance(result, str) and result.endswith(".zip")


class TestArchivePerf:
    def test_already_compressed_formats_are_stored(self, tmp_path):
        src = tmp_path / "p"
        src.mkdir()
        (src / "pic.jpg").write_bytes(b"0" * 5000)
        (src / "code.py").write_bytes(b"0" * 5000)
        out = archive.export_folder_to_zip(src, tmp_path / "o")
        with zipfile.ZipFile(out) as zf:
            kinds = {i.filename.split("/")[-1]: i.compress_type for i in zf.infolist()}
        assert kinds["pic.jpg"] == zipfile.ZIP_STORED and kinds["code.py"] == zipfile.ZIP_DEFLATED

    def test_skipped_files_are_returned(self, tmp_path, monkeypatch):
        src = tmp_path / "p"
        src.mkdir()
        (src / "ok.txt").write_text("1")
        (src / "locked.txt").write_text("2")
        real_open = open

        def fake_open(path, *a, **k):
            if str(path).endswith("locked.txt"):
                raise PermissionError("verrouillé")
            return real_open(path, *a, **k)

        monkeypatch.setattr("builtins.open", fake_open)
        with zipfile.ZipFile(tmp_path / "z.zip", "w") as zf:
            skipped = archive.add_tree_to_zip(zf, src, "p", archive.ProgressTracker(2, None))
        assert skipped == ["locked.txt"]
