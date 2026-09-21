"""Tests de core.archive : extraction ZIP sûre, copie, déplacement, export."""

import errno
import os
import zipfile

import core
import pytest
from core import archive


def _make_zip(path, members: dict[str, bytes | None]):
    """Crée un ZIP ; une valeur None = entrée de dossier."""
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            if data is None:
                zf.writestr(zipfile.ZipInfo(name), b"")
            else:
                zf.writestr(name, data)
    return path


class TestInspectZip:
    def test_single_root_folder_is_detected(self, tmp_path):
        z = _make_zip(tmp_path / "a.zip", {"proj/": None, "proj/main.py": b"x", "proj/lib/u.py": b"yy"})
        info = archive.inspect_zip(z)
        assert info.root_name == "proj"
        assert info.suggested_name == "proj"
        assert info.file_count == 2
        assert info.total_bytes == 3

    def test_files_at_root_use_zip_stem(self, tmp_path):
        z = _make_zip(tmp_path / "monprojet.zip", {"main.py": b"x", "README.md": b"y"})
        info = archive.inspect_zip(z)
        assert info.root_name is None
        assert info.suggested_name == "monprojet"

    def test_several_roots_use_zip_stem(self, tmp_path):
        z = _make_zip(tmp_path / "multi.zip", {"a/f.txt": b"1", "b/g.txt": b"2"})
        assert archive.inspect_zip(z).root_name is None

    @pytest.mark.parametrize("bad", ["../evil.txt", "a/../../evil.txt", "/abs/evil.txt", "C:/evil.txt", "..\\evil.txt"])
    def test_dangerous_member_names_are_rejected(self, tmp_path, bad):
        z = _make_zip(tmp_path / "bad.zip", {bad: b"x"})
        with pytest.raises(core.ArchiveError):
            archive.inspect_zip(z)

    def test_not_a_zip(self, tmp_path):
        f = tmp_path / "fake.zip"
        f.write_text("pas un zip")
        with pytest.raises(core.ArchiveError):
            archive.inspect_zip(f)


class TestExtractZip:
    def test_extracts_into_named_folder_and_strips_single_root(self, tmp_path):
        z = _make_zip(tmp_path / "a.zip", {"proj/main.py": b"print(1)", "proj/pkg/m.py": b"2"})
        out = archive.extract_zip(z, tmp_path / "root")
        assert out == tmp_path / "root" / "proj"
        assert (out / "main.py").read_bytes() == b"print(1)"
        assert (out / "pkg" / "m.py").exists()

    def test_custom_name_overrides_suggestion(self, tmp_path):
        z = _make_zip(tmp_path / "a.zip", {"proj/main.py": b"x"})
        out = archive.extract_zip(z, tmp_path / "root", name="autre")
        assert out.name == "autre" and (out / "main.py").exists()

    def test_flat_zip_is_wrapped_in_a_folder_not_spilled(self, tmp_path):
        # Régression : l'ancien code extrayait « en vrac » dans la racine.
        z = _make_zip(tmp_path / "flat.zip", {"a.txt": b"1", "b.txt": b"2"})
        root = tmp_path / "root"
        out = archive.extract_zip(z, root)
        assert out == root / "flat"
        assert sorted(p.name for p in root.iterdir()) == ["flat"]

    def test_existing_target_raises(self, tmp_path):
        z = _make_zip(tmp_path / "a.zip", {"proj/x": b"1"})
        (tmp_path / "root" / "proj").mkdir(parents=True)
        with pytest.raises(FileExistsError):
            archive.extract_zip(z, tmp_path / "root")

    def test_zip_slip_writes_nothing_outside(self, tmp_path):
        z = _make_zip(tmp_path / "evil.zip", {"ok.txt": b"1", "../pwned.txt": b"x"})
        root = tmp_path / "root"
        with pytest.raises(core.ArchiveError):
            archive.extract_zip(z, root)
        assert not (tmp_path / "pwned.txt").exists()
        assert not list(root.glob(".voktora-tmp-*"))  # staging nettoyé

    def test_progress_is_monotonic_and_reaches_total(self, tmp_path):
        z = _make_zip(tmp_path / "a.zip", {"p/a": b"x" * 5000, "p/b": b"y" * 3000})
        calls = []
        archive.extract_zip(z, tmp_path / "root", on_progress=lambda d, t, c: calls.append((d, t)))
        dones = [d for d, _ in calls]
        assert dones == sorted(dones)
        assert calls[-1] == (8000, 8000)

    def test_cancel_removes_partial_extraction(self, tmp_path):
        z = _make_zip(tmp_path / "a.zip", {f"p/f{i}": b"x" * 100 for i in range(10)})
        root = tmp_path / "root"
        state = {"n": 0}

        def cancel():
            state["n"] += 1
            return state["n"] > 3

        with pytest.raises(core.OperationCancelled):
            archive.extract_zip(z, root, cancel=cancel)
        assert list(root.iterdir()) == []

    def test_symlink_members_are_skipped(self, tmp_path):
        z = tmp_path / "l.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("p/real.txt", b"1")
            link = zipfile.ZipInfo("p/link")
            link.external_attr = (0o120777 << 16)
            zf.writestr(link, "/etc/passwd")
        out = archive.extract_zip(z, tmp_path / "root")
        assert (out / "real.txt").exists()
        assert not (out / "link").exists()

    def test_insufficient_disk_space_is_refused(self, tmp_path, monkeypatch):
        z = _make_zip(tmp_path / "a.zip", {"p/a": b"x" * 1000})
        monkeypatch.setattr(archive.shutil, "disk_usage", lambda _p: type("U", (), {"free": 10})())
        with pytest.raises(core.ArchiveError, match="Espace disque"):
            archive.extract_zip(z, tmp_path / "root")

    def test_lying_header_size_is_detected(self, tmp_path):
        z = _make_zip(tmp_path / "a.zip", {"p/a": b"x" * 100})
        # Falsifie file_size dans le répertoire central (10 au lieu de 100).
        import struct
        raw = bytearray(z.read_bytes())
        central = raw.rfind(b"PK\x01\x02")
        struct.pack_into("<I", raw, central + 24, 10)
        z.write_bytes(bytes(raw))
        with pytest.raises(core.ArchiveError):
            archive.extract_zip(z, tmp_path / "root")


class TestCopyAndMove:
    def _make_tree(self, base):
        (base / "sub").mkdir(parents=True)
        (base / "a.txt").write_text("A")
        (base / "sub" / "b.txt").write_text("B")
        return base

    def test_copy_tree_keeps_source(self, tmp_path):
        src = self._make_tree(tmp_path / "src")
        dst = archive.copy_tree(src, tmp_path / "out" / "dst")
        assert (dst / "sub" / "b.txt").read_text() == "B"
        assert (src / "a.txt").exists()
        assert not list((tmp_path / "out").glob(".voktora-tmp-*"))

    def test_copy_into_itself_is_refused(self, tmp_path):
        src = self._make_tree(tmp_path / "src")
        with pytest.raises(ValueError):
            archive.copy_tree(src, src / "inside")

    def test_move_same_volume_is_a_rename(self, tmp_path):
        src = self._make_tree(tmp_path / "src")
        dst = archive.move_tree(src, tmp_path / "moved")
        assert not src.exists()
        assert (dst / "sub" / "b.txt").read_text() == "B"

    def test_move_across_volumes_copies_then_deletes_source(self, tmp_path, monkeypatch):
        src = self._make_tree(tmp_path / "src")

        real_rename = os.rename

        def fake_rename(a, b):
            # Seul le renommage direct de la source simule un autre volume.
            if str(a) == str(src):
                raise OSError(errno.EXDEV, "cross-device")
            return real_rename(a, b)

        monkeypatch.setattr(archive.os, "rename", fake_rename)
        dst = archive.move_tree(src, tmp_path / "moved")
        assert not src.exists()
        assert (dst / "a.txt").read_text() == "A"

    def test_cancelled_cross_volume_move_leaves_source_intact(self, tmp_path, monkeypatch):
        src = self._make_tree(tmp_path / "src")
        real_rename = os.rename

        def fake_rename(a, b):
            if str(a) == str(src):
                raise OSError(errno.EXDEV, "x")
            return real_rename(a, b)

        monkeypatch.setattr(archive.os, "rename", fake_rename)
        with pytest.raises(core.OperationCancelled):
            archive.move_tree(src, tmp_path / "moved", cancel=lambda: True)
        assert (src / "sub" / "b.txt").read_text() == "B"
        assert not (tmp_path / "moved").exists()

    def test_move_refuses_home_directory(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()
        with pytest.raises(ValueError, match="système ou personnel"):
            archive.move_tree(tmp_path / "home", tmp_path / "elsewhere")

    def test_move_existing_destination_raises(self, tmp_path):
        src = self._make_tree(tmp_path / "src")
        (tmp_path / "dst").mkdir()
        with pytest.raises(FileExistsError):
            archive.move_tree(src, tmp_path / "dst")


class TestExport:
    def test_export_roundtrip_and_no_part_file_left(self, isolated_data_dir, tmp_path):
        src = tmp_path / "proj"
        (src / "d").mkdir(parents=True)
        (src / "d" / "f.txt").write_text("hello")
        out = archive.export_folder_to_zip(src, tmp_path / "out")
        assert out.suffix == ".zip"
        with zipfile.ZipFile(out) as zf:
            assert zf.read("proj/d/f.txt") == b"hello"
        assert not list((tmp_path / "out").glob("*.part"))

    def test_git_config_credentials_are_stripped_in_archive(self, isolated_data_dir, tmp_path):
        src = tmp_path / "proj"
        (src / ".git").mkdir(parents=True)
        (src / ".git" / "config").write_text('[remote "origin"]\n\turl = https://me:ghp_SECRET@github.com/o/r.git\n')
        out = archive.export_folder_to_zip(src, tmp_path / "out")
        with zipfile.ZipFile(out) as zf:
            content = zf.read("proj/.git/config").decode()
        assert "ghp_SECRET" not in content
        assert "https://github.com/o/r.git" in content
        # Le fichier sur disque n'est pas modifié.
        assert "ghp_SECRET" in (src / ".git" / "config").read_text()

    def test_cancelled_export_leaves_no_file(self, isolated_data_dir, tmp_path):
        src = tmp_path / "proj"
        src.mkdir()
        (src / "f").write_text("x")
        with pytest.raises(core.OperationCancelled):
            archive.export_folder_to_zip(src, tmp_path / "out", cancel=lambda: True)
        assert list((tmp_path / "out").iterdir()) == []

    def test_symlinks_are_not_followed(self, isolated_data_dir, tmp_path):
        outside = tmp_path / "secret.txt"
        outside.write_text("TOP")
        src = tmp_path / "proj"
        src.mkdir()
        try:
            os.symlink(outside, src / "link.txt")
        except (OSError, NotImplementedError):
            pytest.skip("liens symboliques indisponibles")
        out = archive.export_folder_to_zip(src, tmp_path / "out")
        with zipfile.ZipFile(out) as zf:
            assert "proj/link.txt" not in zf.namelist()
