"""Les deux implémentations (Rust et Python pur) doivent donner les mêmes résultats."""

from __future__ import annotations

import os
import zlib

import core
import pytest
from core import native, parallel

needs_rust = pytest.mark.skipif(not native.native_available(), reason="extension voktora_native non installée")


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "src"
    (root / "a" / "b").mkdir(parents=True)
    (root / "empty").mkdir()
    (root / "one.txt").write_bytes(b"x" * 1000)
    (root / "a" / "two.bin").write_bytes(os.urandom(300_000))
    (root / "a" / "b" / "three.txt").write_bytes(b"")
    if hasattr(os, "symlink"):
        os.symlink("one.txt", root / "link_to_file")
        os.symlink("a", root / "link_to_dir")
    return root


def _snapshot(root):
    out = {}
    for base, dirs, files in os.walk(root):
        for d in dirs:
            out[os.path.relpath(os.path.join(base, d), root) + "/"] = None
        for f in files:
            path = os.path.join(base, f)
            rel = os.path.relpath(path, root)
            if os.path.islink(path):
                out[rel] = os.readlink(path)
            else:
                with open(path, "rb") as handle:
                    out[rel] = handle.read()
    return out


def test_tree_size_python_counts_links_like_before(tree):
    count, total = native.tree_size_python(tree)
    assert total == 1000 + 300_000
    assert count == 3 + 1       # 3 fichiers + 1 lien vers un fichier ; le lien vers un dossier est ignoré


@needs_rust
def test_tree_size_rust_matches_python(tree):
    assert native.tree_size(tree) == native.tree_size_python(tree)


@needs_rust
def test_copy_tree_rust_copies_everything_and_reports_progress(tree, tmp_path):
    dst = tmp_path / "dst"
    seen = []
    result = native.copy_tree_native(tree, dst, lambda n, name: seen.append(n))
    assert result is not None
    assert _snapshot(dst) == _snapshot(tree)
    assert sum(seen) == 301_000


@needs_rust
def test_copy_tree_rust_preserves_mtime_and_mode(tree, tmp_path):
    target = tree / "one.txt"
    os.utime(target, (1_600_000_000, 1_600_000_000))
    os.chmod(target, 0o750)
    dst = tmp_path / "dst"
    native.copy_tree_native(tree, dst)
    copy = dst / "one.txt"
    assert int(copy.stat().st_mtime) == 1_600_000_000
    assert copy.stat().st_mode & 0o777 == 0o750


@needs_rust
def test_copy_tree_rust_cancellation_raises(tree, tmp_path):
    with pytest.raises(core.OperationCancelled):
        native.copy_tree_native(tree, tmp_path / "dst", cancel=lambda: True)


@needs_rust
def test_copy_tree_rust_missing_source_is_an_oserror(tmp_path):
    with pytest.raises(OSError):
        native.copy_tree_native(tmp_path / "absent", tmp_path / "dst")


def test_archive_copy_and_move_work_with_either_backend(tree, tmp_path, monkeypatch):
    for index, disable in enumerate((False, True)):
        if disable:
            monkeypatch.setattr(native, "_native", None)
        dst = tmp_path / f"copy{index}"
        core.archive.copy_tree(tree, dst)
        assert _snapshot(dst) == _snapshot(tree)


def test_crc32_files_matches_zlib(tree):
    files = [tree / "one.txt", tree / "a" / "two.bin", tree / "absent"]
    expected = [zlib.crc32(files[0].read_bytes()), zlib.crc32(files[1].read_bytes()), None]
    assert native.crc32_files(files) == expected


def test_crc32_files_python_fallback_matches(tree, monkeypatch):
    monkeypatch.setattr(native, "_native", None)
    files = [tree / "one.txt", tree / "a" / "two.bin"]
    assert native.crc32_files(files) == [zlib.crc32(f.read_bytes()) for f in files]


def _square(x):
    return x * x


def test_process_map_keeps_order_and_reports_each_result():
    seen = []
    result = parallel.process_map(_square, list(range(12)), workers=2, on_result=lambda i, r: seen.append(i))
    assert result == [x * x for x in range(12)]
    assert sorted(seen) == list(range(12))


def test_process_map_small_input_runs_serially():
    assert parallel.process_map(_square, [1, 2], workers=4) == [1, 4]


def test_process_map_cancel_raises():
    with pytest.raises(core.OperationCancelled):
        parallel.process_map(_square, list(range(8)), workers=2, cancel=lambda: True)


def test_thread_map_propagates_worker_exception():
    def boom(x):
        if x == 3:
            raise ValueError("trois")
        return x

    with pytest.raises(ValueError, match="trois"):
        parallel.thread_map(boom, list(range(6)), workers=3)
