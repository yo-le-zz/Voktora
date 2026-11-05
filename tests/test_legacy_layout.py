"""Fin de l'ancienne séparation Instances / Intents : détection, déplacement, config."""

from __future__ import annotations

from pathlib import Path

import core
import pytest


def _make_project(parent, name, content="x"):
    folder = parent / name
    folder.mkdir(parents=True)
    (folder / "main.py").write_text(content)
    return folder


@pytest.fixture
def layout(isolated_data_dir, tmp_path, monkeypatch):
    root = tmp_path / "Voktora" / "Projects"
    monkeypatch.setattr(core.drives, "get_available_drives", lambda: [])
    monkeypatch.setattr(core.legacy_layout.Path, "home", classmethod(lambda cls: tmp_path / "home"))
    core.set_storage_config(root)
    return tmp_path / "Voktora", root


def test_nothing_to_do_without_legacy_dirs(layout):
    _container, root = layout
    root.mkdir(parents=True)
    assert core.plan_migration() is None
    assert core.migrate_now() is None


def test_moves_registered_and_unregistered_projects(layout):
    container, root = layout
    a = _make_project(container / "Instances", "alpha")
    b = _make_project(container / "Intents", "beta")
    core.register_project(a, name="alpha")
    core.register_project(b, name="beta")

    plan = core.plan_migration()
    assert plan is not None and plan.destination == root
    assert {m.source.name for m in plan.moves} == {"alpha", "beta"}

    progress = []
    result = core.apply_migration(plan, lambda d, t, s: progress.append((d, t)))
    assert len(result.moved) == 2
    assert (root / "alpha" / "main.py").exists() and (root / "beta" / "main.py").exists()
    assert not (container / "Instances").exists() and not (container / "Intents").exists()
    assert progress and progress[-1][0] == progress[-1][1]
    paths = {e["path"] for e in core.list_projects()}
    assert paths == {str(root / "alpha"), str(root / "beta")}
    assert core.plan_migration() is None


def test_name_collision_never_overwrites(layout):
    container, root = layout
    _make_project(root, "app", "existing")
    old = _make_project(container / "Instances", "app", "legacy")
    core.register_project(old, name="app")

    result = core.migrate_now()
    assert result is not None and len(result.moved) == 1
    assert (root / "app" / "main.py").read_text() == "existing"
    assert (root / "app (2)" / "main.py").read_text() == "legacy"
    assert core.list_projects()[0]["path"] == str(root / "app (2)")


def test_custom_root_named_instances_moves_to_parent(isolated_data_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(core.drives, "get_available_drives", lambda: [])
    legacy_root = tmp_path / "dev" / "Instances"
    project = _make_project(legacy_root, "tool")
    core.set_storage_config(legacy_root)
    core.register_project(project, name="tool")

    result = core.migrate_now()
    assert result is not None
    assert (tmp_path / "dev" / "tool" / "main.py").exists()
    assert not legacy_root.exists()
    assert core.get_storage_config()["projects_root"] == str(tmp_path / "dev")


def test_stray_files_keep_the_legacy_dir(layout):
    container, _root = layout
    _make_project(container / "Intents", "p")
    (container / "Intents" / "notes.txt").write_text("keep me")

    result = core.migrate_now()
    assert result is not None
    assert (container / "Intents" / "notes.txt").exists()
    assert result.leftovers == [container / "Intents"]


def test_cancellation_keeps_config_consistent(layout):
    container, _root = layout
    a = _make_project(container / "Instances", "a")
    b = _make_project(container / "Instances", "b")
    core.register_project(a, name="a")
    core.register_project(b, name="b")
    plan = core.plan_migration()
    calls = {"n": 0}

    def cancel():
        calls["n"] += 1
        return calls["n"] > 1       # annule avant le 2e projet

    with pytest.raises(core.OperationCancelled):
        core.apply_migration(plan, cancel=cancel)
    for entry in core.list_projects():
        assert Path(entry["path"]).is_dir()
