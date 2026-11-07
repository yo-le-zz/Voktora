"""Snapshots 1.0.7 : sauvegarde complète versionnée, vérification, restauration, comparaison intelligente."""

import json
import os
import zipfile

import core
import pytest
import snapshots as sn


@pytest.fixture
def project(tmp_path, isolated_data_dir):
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text("print('a')\nprint('b')\n")
    (root / "notes.txt").write_text("hello\n")
    (root / "pyproject.toml").write_text("[project]\n")
    (root / ".git" / "refs" / "heads").mkdir(parents=True)
    (root / ".git" / "HEAD").write_text("ref: refs/heads/dev\n")
    (root / ".git" / "refs" / "heads" / "dev").write_text("a" * 40 + "\n")
    (root / ".git" / "objects").mkdir()
    (root / ".git" / "objects" / "obj").write_bytes(b"o" * 50)
    (root / "node_modules" / "x").mkdir(parents=True)
    (root / "node_modules" / "x" / "i.js").write_text("x" * 1000)
    (root / "package.json").write_text("{}")
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "a.pyc").write_bytes(b"c" * 10)
    return root


class TestCreate:
    def test_complete_backup_metadata_and_exclusions(self, project):
        snap = sn.create(project, note="avant refactor")
        info = sn.list_snaps(project)[0]
        assert info.version == 1 and info.label == "v1" and info.note == "avant refactor"
        assert info.git_branch == "dev" and info.git_commit == "a" * 40 and info.includes_git
        assert info.files == 7 and info.bytes > 0
        assert {e["path"] for e in info.excluded} == {"node_modules", "__pycache__"}
        names = zipfile.ZipFile(snap).namelist()
        assert "files/.git/objects/obj" in names and "files/src/a.py" in names
        assert not any("node_modules" in n or "__pycache__" in n for n in names)
        assert "index.json" in names

    def test_options_include_everything_or_exclude_git(self, project):
        full = sn.create(project, include_regenerable=True)
        assert any("node_modules" in n for n in zipfile.ZipFile(full).namelist())
        no_git = sn.create(project, include_git=False)
        names = zipfile.ZipFile(no_git).namelist()
        assert not any(n.startswith("files/.git") for n in names)
        assert any(e["path"] == ".git" for e in sn.read_manifest(no_git)["excluded"])

    def test_versions_increment_and_prune(self, project):
        for _ in range(4):
            sn.create(project)
        assert [s.version for s in sn.list_snaps(project)] == [4, 3, 2, 1]
        removed = sn.prune(project, keep=2)
        assert len(removed) == 2 and [s.version for s in sn.list_snaps(project)] == [4, 3]
        sn.create(project, keep=2)
        assert [s.version for s in sn.list_snaps(project)] == [5, 4]
        assert sn.prune(project, keep=0) == []

    def test_progress_reaches_total(self, project):
        seen = []
        sn.create(project, on_progress=lambda *a: seen.append(a))
        assert seen and seen[-1] is not None

    def test_no_secret_in_project_meta(self, project, isolated_data_dir):
        snap = sn.create(project)
        text = json.dumps(sn.read_manifest(snap)["project_meta"])
        assert "token" not in text.lower()

    def test_symlinks_ignored(self, project, tmp_path):
        (tmp_path / "secret.txt").write_text("SECRET")
        (project / "link.txt").symlink_to(tmp_path / "secret.txt")
        blob = b"".join(zipfile.ZipFile(sn.create(project)).read(n) for n in zipfile.ZipFile(sn.create(project)).namelist())
        assert b"SECRET" not in blob


class TestVerify:
    def test_intact_and_tampered(self, project, tmp_path):
        snap = sn.create(project)
        assert sn.verify(snap) == []
        evil = tmp_path / "evil.snap"
        with zipfile.ZipFile(snap) as src, zipfile.ZipFile(evil, "w") as dst:
            for item in src.infolist():
                data = src.read(item)
                if item.filename == "files/src/a.py":
                    data = b"print('tampered')\n"
                dst.writestr(item.filename, data)
        problems = sn.verify(evil)
        assert any("a.py" in p and "empreinte" in p for p in problems)

    def test_missing_member_and_garbage(self, project, tmp_path):
        garbage = tmp_path / "g.snap"
        garbage.write_bytes(b"not a zip")
        assert "illisible" in sn.verify(garbage)[0]


class TestRestore:
    def test_restore_in_place_makes_safety_snapshot(self, project):
        snap = sn.create(project, "ok")
        (project / "src" / "a.py").write_text("BROKEN")
        (project / "extra.txt").write_text("e")
        safety = sn.restore_in_place(snap, project)
        assert (project / "src" / "a.py").read_text().startswith("print('a')")
        assert not (project / "extra.txt").exists()
        assert safety and sn.read_manifest(safety)["kind"] == sn.KIND_SAFETY
        # le snapshot de sécurité contient l'état d'avant la restauration
        assert b"BROKEN" in zipfile.ZipFile(safety).read("files/src/a.py")

    def test_restore_in_place_without_safety(self, project):
        snap = sn.create(project)
        assert sn.restore_in_place(snap, project, safety=False) is None
        assert len(sn.list_snaps(project)) == 1

    def test_restore_selected_files_only(self, project):
        snap = sn.create(project)
        (project / "src" / "a.py").write_text("CHANGED")
        (project / "notes.txt").write_text("CHANGED TOO")
        assert sn.restore_files(snap, project, ["src/a.py", "does/not/exist"]) == ["src/a.py"]
        assert (project / "src" / "a.py").read_text().startswith("print('a')")
        assert (project / "notes.txt").read_text() == "CHANGED TOO"

    def test_restore_files_rejects_traversal(self, project, tmp_path):
        evil = tmp_path / "e.snap"
        with zipfile.ZipFile(evil, "w") as zf:
            zf.writestr("manifest.json", "{}")
            zf.writestr("files/../../pwn.txt", "x")
        with pytest.raises(core.ArchiveError):
            sn.restore_files(evil, project, ["../../pwn.txt"])
        assert not (project.parent.parent / "pwn.txt").exists()

    def test_cancelled_restore_keeps_project(self, project):
        snap = sn.create(project)
        (project / "notes.txt").write_text("mine")
        with pytest.raises(core.OperationCancelled):
            sn.restore(snap, project, overwrite=True, cancel=lambda: True)
        assert (project / "notes.txt").read_text() == "mine"


class TestCompare:
    def test_renames_between_snapshots(self, project):
        a = sn.create(project)
        os.rename(project / "notes.txt", project / "README.txt")
        (project / "src" / "a.py").write_text("print('changed')\n")
        (project / "new.md").write_text("new")
        b = sn.create(project)
        cmp = sn.compare(a, b)
        status = {c.path: c for c in cmp.changes}
        assert status["README.txt"].status == "renamed" and status["README.txt"].old_path == "notes.txt"
        assert status["src/a.py"].status == "modified" and status["new.md"].status == "added"
        assert "notes.txt" not in status
        assert "1 renommé" in cmp.summary() and cmp.unchanged >= 2
        # l'ancienne API reste disponible et sans détection de renommage
        old_style = sn.diff_snaps(a, b)
        assert old_style["notes.txt"] == "removed" and old_style["README.txt"] == "added"

    def test_snapshot_vs_current_state(self, project):
        snap = sn.create(project)
        assert sn.compare(snap, None, project).changes == []        # rien n'a changé (caches exclus, .git ignoré)
        (project / "src" / "a.py").write_text("print('x')\n")
        (project / "added.txt").write_text("a")
        (project / "notes.txt").unlink()
        (project / "node_modules" / "x" / "i.js").write_text("changed deps")   # exclu du snapshot : ignoré
        status = sn.compare(snap, None, project).as_dict()
        assert status == {"src/a.py": "modified", "added.txt": "added", "notes.txt": "removed"}

    def test_live_rename_detected(self, project):
        snap = sn.create(project)
        os.rename(project / "notes.txt", project / "docs.txt")
        cmp = sn.compare(snap, None, project)
        assert [(c.status, c.old_path) for c in cmp.changes] == [("renamed", "notes.txt")]

    def test_requires_second_source(self, project):
        with pytest.raises(ValueError):
            sn.compare(sn.create(project))

    def test_file_diff(self, project):
        a = sn.create(project)
        (project / "src" / "a.py").write_text("print('a')\nprint('NEW')\n")
        diff = sn.file_diff(a, "src/a.py", project_path=project)
        assert "+print('NEW')" in diff and "--- a/src/a.py" in diff
        (project / "blob.bin").write_bytes(b"\0\1\2")
        b = sn.create(project)
        assert "binaire" in sn.file_diff(b, "blob.bin", project_path=project)
        assert sn.file_diff(a, "notes.txt", project_path=project) == "(contenu identique)"

    def test_legacy_v1_snapshot_still_listed_and_compared(self, project, tmp_path):
        legacy_dir = core.get_data_dir() / "snapshots" / project.name
        legacy_dir.mkdir(parents=True)
        legacy = legacy_dir / "proj_20200101_000000.snap"
        with zipfile.ZipFile(legacy, "w") as zf:
            zf.writestr("manifest.json", json.dumps({"version": 1, "label": "old", "timestamp": "20200101_000000"}))
            zf.writestr("files/notes.txt", "hello\n")
        info = sn.list_snaps(project)[0]
        assert info.label == "old" and info.format == 1 and info.version == 0
        assert sn.compare(legacy, None, project).count("added") >= 1
        assert sn.create(project) and sn.next_version(project) == 2
