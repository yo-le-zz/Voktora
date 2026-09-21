import core


class TestTransferProject:
    def test_instance_to_intent_round_trip(self, isolated_data_dir, tmp_path):
        core.set_storage_config(str(tmp_path / "Instances"), str(tmp_path / "Intents"))
        drive = str(tmp_path)

        path = core.create_instance(drive, "SwitchMe")
        assert any(i["name"] == "SwitchMe" for i in core.list_instances())

        new_path = core.transfer_project(path, "instance", "intent")
        assert new_path.exists()
        assert not path.exists()
        assert any(i["name"] == "SwitchMe" for i in core.list_intents())
        assert not any(i["name"] == "SwitchMe" for i in core.list_instances())

        # Et dans l'autre sens
        back_path = core.transfer_project(new_path, "intent", "instance")
        assert back_path.exists()
        assert any(i["name"] == "SwitchMe" for i in core.list_instances())

    def test_transfer_same_kind_raises(self, isolated_data_dir, tmp_path):
        core.set_storage_config(str(tmp_path / "Instances"), str(tmp_path / "Intents"))
        path = core.create_instance(str(tmp_path), "SameKind")
        try:
            core.transfer_project(path, "instance", "instance")
            raise AssertionError("aurait dû lever ValueError")
        except ValueError:
            pass

    def test_transfer_conflict_raises_file_exists(self, isolated_data_dir, tmp_path):
        core.set_storage_config(str(tmp_path / "Instances"), str(tmp_path / "Intents"))
        drive = str(tmp_path)
        path = core.create_instance(drive, "Conflict")
        core.create_intent(drive, "Conflict")
        try:
            core.transfer_project(path, "instance", "intent")
            raise AssertionError("aurait dû lever FileExistsError")
        except FileExistsError:
            pass

    def test_transfer_strips_github_fields_when_becoming_intent(self, isolated_data_dir, tmp_path):
        core.set_storage_config(str(tmp_path / "Instances"), str(tmp_path / "Intents"))
        path = core.create_instance(str(tmp_path), "HadGithub")
        core.set_instance_repo(path, "https://github.com/x/y")

        new_path = core.transfer_project(path, "instance", "intent")
        entry = next(i for i in core.list_intents() if i["name"] == "HadGithub")
        assert "github_repo" not in entry
        assert new_path  # sanity
