import core


class TestImportFromFolder:
    def test_imports_folder_and_registers_entry(self, isolated_data_dir, tmp_path):
        core.set_storage_config(str(tmp_path / "Instances"), str(tmp_path / "Intents"))

        source = tmp_path / "external_project"
        source.mkdir()
        (source / "main.py").write_text("print('hi')\n")

        dest = core.import_from_folder(source, str(tmp_path), "instance")

        assert dest.exists()
        assert (dest / "main.py").exists()
        assert source.exists()  # dossier source jamais supprimé
        assert any(i["name"] == "external_project" for i in core.list_instances())

    def test_source_folder_untouched_after_import(self, isolated_data_dir, tmp_path):
        core.set_storage_config(str(tmp_path / "Instances"), str(tmp_path / "Intents"))
        source = tmp_path / "keepme"
        source.mkdir()
        (source / "data.txt").write_text("original")

        core.import_from_folder(source, str(tmp_path), "intent")

        assert (source / "data.txt").read_text() == "original"

    def test_raises_if_not_a_directory(self, isolated_data_dir, tmp_path):
        core.set_storage_config(str(tmp_path / "Instances"), str(tmp_path / "Intents"))
        not_a_dir = tmp_path / "file.txt"
        not_a_dir.write_text("x")
        try:
            core.import_from_folder(not_a_dir, str(tmp_path), "instance")
            raise AssertionError("aurait dû lever NotADirectoryError")
        except NotADirectoryError:
            pass

    def test_raises_on_name_conflict(self, isolated_data_dir, tmp_path):
        core.set_storage_config(str(tmp_path / "Instances"), str(tmp_path / "Intents"))
        source = tmp_path / "dup"
        source.mkdir()
        core.import_from_folder(source, str(tmp_path), "instance")

        source2 = tmp_path / "other" / "dup"
        source2.mkdir(parents=True)
        try:
            core.import_from_folder(source2, str(tmp_path), "instance")
            raise AssertionError("aurait dû lever FileExistsError")
        except FileExistsError:
            pass
