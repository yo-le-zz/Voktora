"""Vue d'ensemble des projets : état Git, actions groupées, recherche globale, orphelins (1.1.0)."""

import subprocess
from pathlib import Path

import core
import fleet
import pytest


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *args], check=True,
                   capture_output=True)


def make_repo(path: Path, files=None):
    path.mkdir(parents=True)
    git(path, "init", "-b", "main")
    for rel, text in (files or {"a.txt": "bonjour\n"}).items():
        (path / rel).parent.mkdir(parents=True, exist_ok=True)
        (path / rel).write_text(text)
    git(path, "add", ".")
    git(path, "commit", "-m", "init")
    return path


@pytest.fixture
def world(isolated_data_dir, tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(remote)], check=True, capture_output=True)
    clean = make_repo(tmp_path / "propre", {"main.py": "print('salut monde')\n", "doc/notes.md": "TODO trouver Voktora\n"})
    git(clean, "remote", "add", "origin", str(remote))
    git(clean, "push", "-u", "origin", "main")
    dirty = make_repo(tmp_path / "sale")
    (dirty / "a.txt").write_text("modifié\n")
    (dirty / "new.txt").write_text("x\n")
    norem = make_repo(tmp_path / "sansremote")
    plain = tmp_path / "pasgit"
    plain.mkdir()
    (plain / "f.txt").write_text("hello\n")
    for name, p in (("propre", clean), ("sale", dirty), ("sansremote", norem), ("pasgit", plain), ("absent", tmp_path / "absent")):
        core.register_project(p, name=name)
    return {"remote": remote, "clean": clean, "dirty": dirty, "tmp": tmp_path}


def test_scan_states(world):
    states = {s.name: s for s in fleet.scan_all(workers=3)}
    assert states["propre"].clean and states["propre"].branch == "main"
    assert states["sale"].dirty == 1 and states["sale"].untracked == 1 and "2 modification" in states["sale"].problems[0]
    assert "sans dépôt distant" in states["sansremote"].problems
    assert states["pasgit"].problems == ["pas de dépôt Git"] and states["absent"].problems == ["dossier manquant"]
    summ = fleet.summary(list(states.values()))
    assert summ["total"] == 5 and summ["clean"] == 1 and summ["missing"] == 1 and summ["not_git"] == 1


def test_scan_detects_ahead_and_behind(world):
    clone = world["tmp"] / "clone"
    subprocess.run(["git", "clone", str(world["remote"]), str(clone)], check=True, capture_output=True)
    (clone / "n.txt").write_text("n\n")
    git(clone, "add", ".")
    git(clone, "commit", "-m", "autre PC")
    git(clone, "push")
    assert fleet.scan_repo("propre", world["clean"]).behind == 0         # pas encore de fetch : inconnu localement
    res = fleet.bulk("fetch", [("propre", str(world["clean"]))])
    assert res[0]["ok"] and fleet.scan_repo("propre", world["clean"]).behind == 1
    res = fleet.bulk("pull", [("propre", str(world["clean"]))])
    assert res[0]["ok"] and (world["clean"] / "n.txt").exists() and fleet.scan_repo("p", world["clean"]).behind == 0


def test_bulk_pull_skips_dirty_and_non_git(world):
    res = {r["name"]: r for r in fleet.bulk("pull", [("sale", str(world["dirty"])), ("pasgit", str(world["tmp"] / "pasgit"))])}
    assert res["sale"]["skipped"] and "modifications locales" in res["sale"]["message"]
    assert res["pasgit"]["skipped"]
    with pytest.raises(ValueError):
        fleet.bulk("push", [])                                            # aucun push depuis Voktora


def test_global_search_names_files_and_content(world):
    hits = fleet.search("notes")
    assert any(h.kind == "fichier" and h.path == "doc/notes.md" for h in hits)
    assert any(h.kind == "projet" for h in fleet.search("propre"))
    content = fleet.search("salut monde")
    assert any(h.kind == "contenu" and h.path == "main.py" and h.line == 1 for h in content)
    assert fleet.search("a") == []                                       # requête trop courte
    assert not any(".git/" in h.path for h in fleet.search("init"))      # le dossier .git est ignoré


def test_search_python_fallback_matches_ripgrep_free_path(world, monkeypatch):
    monkeypatch.setattr(fleet.shutil, "which", lambda name: None)
    assert any(h.kind == "contenu" and "salut" in h.text for h in fleet.search("SALUT MONDE"))


def test_orphans(world, monkeypatch):
    root = world["tmp"] / "racine"
    root.mkdir()
    monkeypatch.setattr(core, "get_projects_root", lambda: root)
    (root / "copie-a-la-main").mkdir()
    (root / "_cache").mkdir()
    assert [Path(p).name for p in fleet.find_orphans()] == ["copie-a-la-main"]
