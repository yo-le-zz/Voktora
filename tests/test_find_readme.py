import core


class TestFindReadme:
    def test_finds_readme_md(self, tmp_path):
        (tmp_path / "README.md").write_text("# Titre")
        assert core.find_readme(tmp_path).name == "README.md"

    def test_case_insensitive(self, tmp_path):
        (tmp_path / "readme.MD").write_text("# Titre")
        assert core.find_readme(tmp_path) is not None

    def test_prefers_md_over_txt(self, tmp_path):
        (tmp_path / "README.txt").write_text("texte")
        (tmp_path / "README.md").write_text("# md")
        assert core.find_readme(tmp_path).name == "README.md"

    def test_returns_none_when_absent(self, tmp_path):
        assert core.find_readme(tmp_path) is None

    def test_returns_none_for_non_directory(self, tmp_path):
        f = tmp_path / "not_a_dir.txt"
        f.write_text("x")
        assert core.find_readme(f) is None
