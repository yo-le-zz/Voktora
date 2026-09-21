import subprocess

import git
import pytest


def _init_repo(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)


@pytest.fixture
def repo(tmp_path):
    _init_repo(tmp_path)
    return tmp_path


class TestSmartCommitMessage:
    def test_no_changes_returns_chore_update(self, repo):
        assert git.smart_commit_message(repo) == "chore: update"

    def test_detects_feat_for_source_files(self, repo):
        (repo / "main.py").write_text("print('hi')\n")
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        msg = git.smart_commit_message(repo)
        assert msg.startswith("feat")
        assert "main.py" in msg

    def test_detects_docs_for_markdown(self, repo):
        (repo / "README.md").write_text("# Title\n")
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        assert git.smart_commit_message(repo).startswith("docs")

    def test_detects_test_files(self, repo):
        (repo / "test_something.py").write_text("def test_x(): pass\n")
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        assert git.smart_commit_message(repo).startswith("test")

    def test_truncates_file_list_beyond_three(self, repo):
        for i in range(5):
            (repo / f"file{i}.py").write_text("x = 1\n")
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        msg = git.smart_commit_message(repo)
        assert "+2 more" in msg

    def test_includes_scope_from_common_directory(self, repo):
        (repo / "src").mkdir()
        (repo / "src" / "a.py").write_text("x = 1\n")
        (repo / "src" / "b.py").write_text("y = 2\n")
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        msg = git.smart_commit_message(repo)
        assert msg.startswith("feat(src):")


class TestAutoCommit:
    def test_returns_false_without_git_repo(self, tmp_path):
        assert git.auto_commit(tmp_path) is False

    def test_returns_false_with_nothing_to_commit(self, repo):
        assert git.auto_commit(repo) is False

    def test_commits_new_file(self, repo):
        (repo / "a.py").write_text("x = 1\n")
        assert git.auto_commit(repo) is True
        log = git.get_log(repo, n=1)
        assert "feat" in log
