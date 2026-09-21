"""Tests de core.projects : création, import zip/dossier, clone, oubli, ordre."""

import zipfile

import core
import pytest


@pytest.fixture
def root(isolated_data_dir, tmp_path):
    core.set_storage_config(str(tmp_path / "Projects"))
    return tmp_path / "Projects"


def _zip(path, members):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return path


class TestCreate:
    def test_create_registers_project_with_defaults(self, root, tmp_path):
        p = core.create_project(str(tmp_path), "Alpha")
        assert p == root / "Alpha" and p.is_dir()
        entry = core.get_project(p)
        assert entry["name"] == "Alpha" and entry["category"] is None
        assert entry["github_branch"] == "main"

    def test_create_with_category_creates_it(self, root, tmp_path):
        p = core.create_project(str(tmp_path), "Beta", category="Web")
        assert core.get_project(p)["category"] == "Web"
        assert [c["name"] for c in core.list_categories()] == ["Web"]

    def test_create_with_github_repo_strips_credentials(self, root, tmp_path):
        p = core.create_project(str(tmp_path), "Gamma", github_repo="https://me:tok@github.com/o/g.git")
        assert core.get_project(p)["github_repo"] == "https://github.com/o/g.git"

    def test_create_rejects_bad_repo_url(self, root, tmp_path):
        with pytest.raises(ValueError):
            core.create_project(str(tmp_path), "Delta", github_repo="ext::sh -c evil")

    def test_duplicate_name_raises(self, root, tmp_path):
        core.create_project(str(tmp_path), "Same")
        with pytest.raises(FileExistsError):
            core.create_project(str(tmp_path), "Same")

    def test_forget_keeps_folder_delete_removes_it(self, root, tmp_path):
        a = core.create_project(str(tmp_path), "A")
        b = core.create_project(str(tmp_path), "B")
        core.forget_project(a)
        core.delete_project(b)
        assert a.exists() and not b.exists()
        assert core.list_projects() == []

    def test_rename_updates_entry(self, root, tmp_path):
        p = core.create_project(str(tmp_path), "Old")
        new = core.rename_project(p, "New")
        assert core.get_project(new)["name"] == "New" and not p.exists()

    def test_reorder_persists_and_keeps_unlisted(self, root, tmp_path):
        paths = [str(core.create_project(str(tmp_path), n)) for n in ("a", "b", "c")]
        core.reorder_projects([paths[2], paths[0]])
        assert [e["name"] for e in core.list_projects()] == ["c", "a", "b"]


class TestImportZip:
    def test_import_registers_and_uses_root_folder_name(self, root):
        z = _zip(root.parent / "x.zip", {"monproj/main.py": "print(1)"})
        dest = core.import_from_zip(z, str(root.parent), category="Import")
        assert dest == root / "monproj" and (dest / "main.py").exists()
        entry = core.get_project(dest)
        assert entry["name"] == "monproj" and entry["category"] == "Import"

    def test_custom_name(self, root):
        z = _zip(root.parent / "x.zip", {"monproj/main.py": "1"})
        assert core.import_from_zip(z, str(root.parent), name="autre").name == "autre"

    def test_git_origin_of_zipped_project_is_picked_up(self, root):
        z = _zip(root.parent / "g.zip", {
            "p/.git/config": '[remote "origin"]\n\turl = https://me:tok@github.com/acme/p.git\n',
            "p/.git/HEAD": "ref: refs/heads/dev\n",
            "p/a.txt": "1",
        })
        entry = core.get_project(core.import_from_zip(z, str(root.parent)))
        assert entry["github_repo"] == "https://github.com/acme/p.git"
        assert entry["github_branch"] == "dev"

    def test_failed_import_leaves_nothing(self, root):
        z = _zip(root.parent / "evil.zip", {"../x": "1"})
        with pytest.raises(core.ArchiveError):
            core.import_from_zip(z, str(root.parent))
        assert core.list_projects() == []
        assert not root.exists() or list(root.iterdir()) == []


class TestImportFolder:
    def _source(self, tmp_path, name="ext"):
        src = tmp_path / "elsewhere" / name
        src.mkdir(parents=True)
        (src / "main.py").write_text("print('hi')\n")
        return src

    def test_move_is_default_and_removes_source(self, root, tmp_path):
        src = self._source(tmp_path)
        dest = core.import_from_folder(src, str(tmp_path))
        assert dest == root / "ext" and (dest / "main.py").exists()
        assert not src.exists()
        assert core.get_project(dest)["name"] == "ext"

    def test_copy_keeps_source(self, root, tmp_path):
        src = self._source(tmp_path)
        dest = core.import_from_folder(src, str(tmp_path), mode=core.IMPORT_COPY)
        assert src.exists() and (dest / "main.py").exists()

    def test_link_registers_in_place(self, root, tmp_path):
        src = self._source(tmp_path)
        dest = core.import_from_folder(src, str(tmp_path), mode=core.IMPORT_LINK, category="Perso")
        assert dest == src and (src / "main.py").exists()
        assert core.get_project(src)["category"] == "Perso"

    def test_link_twice_is_refused(self, root, tmp_path):
        src = self._source(tmp_path)
        core.import_from_folder(src, str(tmp_path), mode=core.IMPORT_LINK)
        with pytest.raises(ValueError, match="déjà enregistré"):
            core.import_from_folder(src, str(tmp_path), mode=core.IMPORT_LINK)

    def test_custom_name(self, root, tmp_path):
        src = self._source(tmp_path)
        assert core.import_from_folder(src, str(tmp_path), name="renomme").name == "renomme"

    def test_name_conflict_leaves_source_untouched(self, root, tmp_path):
        (root / "ext").mkdir(parents=True)
        src = self._source(tmp_path)
        with pytest.raises(FileExistsError):
            core.import_from_folder(src, str(tmp_path))
        assert (src / "main.py").exists()

    def test_folder_already_in_root_is_refused_for_move(self, root, tmp_path):
        inside = root / "deja"
        inside.mkdir(parents=True)
        with pytest.raises(ValueError, match="déjà dans le dossier des projets"):
            core.import_from_folder(inside, str(tmp_path))

    def test_not_a_directory(self, root, tmp_path):
        with pytest.raises(NotADirectoryError):
            core.import_from_folder(tmp_path / "nope", str(tmp_path))

    def test_unknown_mode(self, root, tmp_path):
        with pytest.raises(ValueError):
            core.import_from_folder(self._source(tmp_path), str(tmp_path), mode="teleport")

    def test_cancelled_copy_leaves_no_project(self, root, tmp_path):
        src = self._source(tmp_path)
        with pytest.raises(core.OperationCancelled):
            core.import_from_folder(src, str(tmp_path), mode=core.IMPORT_COPY, cancel=lambda: True)
        assert core.list_projects() == [] and (src / "main.py").exists()

    def test_git_origin_is_picked_up(self, root, tmp_path):
        src = self._source(tmp_path)
        (src / ".git").mkdir()
        (src / ".git" / "config").write_text('[remote "origin"]\n\turl = git@github.com:acme/ext.git\n')
        entry = core.get_project(core.import_from_folder(src, str(tmp_path)))
        assert entry["github_repo"] == "git@github.com:acme/ext.git"


class TestExportAll:
    def test_export_all_has_no_secrets_and_all_projects(self, root, tmp_path):
        p = core.create_project(str(tmp_path), "Zed")
        (p / "f.txt").write_text("data")
        core.set_project_token(p, "ghp_TOPSECRET")
        core.save_github_account(token="ghp_ACCOUNT", user_info={"login": "octocat"})
        out = core.export_all_to_zip()
        with zipfile.ZipFile(out) as zf:
            assert "projects/Zed/f.txt" in zf.namelist()
            config = zf.read("config.json").decode()
        assert "ghp_TOPSECRET" not in config
        assert "ghp_ACCOUNT" not in config
        assert "github_account" not in config
