"""Snapshots : restauration sûre (zip-slip), échange atomique, diff par CRC."""

import zipfile

import core
import pytest
import snapshots


@pytest.fixture
def project(tmp_path, isolated_data_dir):
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text("print('a')")
    (root / "img.png").write_bytes(b"\x89PNG" + b"0" * 100)
    (root / ".git" / "objects").mkdir(parents=True)
    (root / ".git" / "objects" / "big").write_bytes(b"x" * 100)
    (root / ".git" / "config").write_text("[remote]\n url = https://user:tok@github.com/o/r.git\n")
    return root


def _evil_snap(path, member):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(snapshots.SNAP_MANIFEST, "{}")
        zf.writestr(member, "pwned")
    return path


class TestCreateRestore:
    def test_round_trip_excludes_git_objects_and_strips_credentials(self, project, tmp_path):
        snap = snapshots.create(project, "v1")
        with zipfile.ZipFile(snap) as zf:
            names = zf.namelist()
            assert "files/src/a.py" in names and "files/.git/objects/big" not in names
            assert b"tok@" not in zf.read("files/.git/config")
        dest = snapshots.restore(snap, tmp_path / "restored")
        assert (dest / "src" / "a.py").read_text() == "print('a')"

    def test_restore_refuses_existing_without_overwrite(self, project, tmp_path):
        snap = snapshots.create(project)
        (tmp_path / "t").mkdir()
        with pytest.raises(FileExistsError):
            snapshots.restore(snap, tmp_path / "t")

    @pytest.mark.parametrize("member", ["files/../../escape.txt", "files//etc/evil", "files/C:/evil.txt"])
    def test_zip_slip_is_blocked(self, tmp_path, member):
        snap = _evil_snap(tmp_path / "evil.snap", member)
        target = tmp_path / "out" / "proj"
        with pytest.raises(core.ArchiveError):
            snapshots.restore(snap, target)
        assert not (tmp_path / "escape.txt").exists()
        assert not target.exists()
        assert [p.name for p in (tmp_path / "out").iterdir()] == [] if (tmp_path / "out").exists() else True

    def test_failed_overwrite_keeps_previous_content(self, tmp_path):
        target = tmp_path / "proj"
        target.mkdir()
        (target / "keep.txt").write_text("precieux")
        snap = _evil_snap(tmp_path / "evil.snap", "files/../x")
        with pytest.raises(core.ArchiveError):
            snapshots.restore(snap, target, overwrite=True)
        assert (target / "keep.txt").read_text() == "precieux"

    def test_overwrite_replaces_content(self, project, tmp_path):
        snap = snapshots.create(project)
        target = tmp_path / "dest"
        target.mkdir()
        (target / "old.txt").write_text("old")
        snapshots.restore(snap, target, overwrite=True)
        assert not (target / "old.txt").exists() and (target / "src" / "a.py").exists()
        assert not (tmp_path / "dest.voktora-old").exists()

    def test_cancelled_create_leaves_no_archive(self, project):
        with pytest.raises(core.OperationCancelled):
            snapshots.create(project, cancel=lambda: True)
        assert snapshots.list_snaps(project) == []


class TestDiff:
    def test_added_removed_modified(self, project):
        a = snapshots.create(project, "a")
        (project / "src" / "a.py").write_text("print('changed!')")
        (project / "new.txt").write_text("n")
        (project / "img.png").unlink()
        b = snapshots.create(project, "b")
        assert snapshots.diff_snaps(a, b) == {"src/a.py": "modified", "new.txt": "added", "img.png": "removed"}
