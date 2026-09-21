"""Sécurité git : le token ne doit jamais être écrit dans un remote ni dans les arguments."""

import base64
import subprocess

import core
import pytest
from core import git_ops


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


class TestAuthEnv:
    def test_no_token_means_no_custom_env(self):
        assert git_ops._auth_env("") is None

    def test_header_is_scoped_to_github_and_encodes_token(self, monkeypatch):
        monkeypatch.delenv("GIT_CONFIG_COUNT", raising=False)
        env = git_ops._auth_env("ghp_abc")
        assert env["GIT_CONFIG_COUNT"] == "1"
        assert env["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"
        encoded = base64.b64encode(b"x-access-token:ghp_abc").decode()
        assert env["GIT_CONFIG_VALUE_0"] == f"AUTHORIZATION: basic {encoded}"
        assert env["GIT_TERMINAL_PROMPT"] == "0"

    def test_existing_git_config_env_is_preserved(self, monkeypatch):
        monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
        monkeypatch.setenv("GIT_CONFIG_KEY_0", "user.name")
        monkeypatch.setenv("GIT_CONFIG_VALUE_0", "x")
        env = git_ops._auth_env("tok")
        assert env["GIT_CONFIG_COUNT"] == "2"
        assert env["GIT_CONFIG_KEY_0"] == "user.name"
        assert env["GIT_CONFIG_KEY_1"].endswith(".extraheader")

    def test_redact_hides_token_and_its_encoding(self):
        encoded = base64.b64encode(b"x-access-token:ghp_abc").decode()
        assert git_ops._redact(f"boom ghp_abc and {encoded}", "ghp_abc") == "boom *** and ***"


class TestValidation:
    @pytest.mark.parametrize("url", [
        "https://github.com/a/b.git", "http://example.com/a/b", "ssh://git@github.com/a/b.git",
        "git@github.com:a/b.git", "git://host/x.git",
    ])
    def test_accepts_normal_urls(self, url):
        assert git_ops.validate_clone_url(url) == url

    @pytest.mark.parametrize("url", ["", "--upload-pack=touch /tmp/x", "ext::sh -c evil", "file:///etc", "/local/path", "-oProxyCommand=x"])
    def test_rejects_dangerous_urls(self, url):
        with pytest.raises(ValueError):
            git_ops.validate_clone_url(url)

    def test_credentials_are_stripped(self):
        assert git_ops.validate_clone_url("https://u:tok@github.com/a/b.git") == "https://github.com/a/b.git"

    @pytest.mark.parametrize("ref", ["-D", "--force", "a..b", "x.lock", "", "bad name", "a;b"])
    def test_rejects_dangerous_refs(self, ref):
        with pytest.raises(ValueError):
            git_ops.validate_ref(ref)

    @pytest.mark.parametrize("ref", ["main", "feature/x-1", "release_1.2"])
    def test_accepts_normal_refs(self, ref):
        assert git_ops.validate_ref(ref) == ref


class TestPushDoesNotPersistToken:
    def test_remote_url_is_clean_after_push_setup(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        _git("init", "-q", cwd=repo)
        _git("config", "user.email", "t@t", cwd=repo)
        _git("config", "user.name", "t", cwd=repo)
        (repo / "a.txt").write_text("1")
        # Remote existant qui contenait un token (ancien comportement) : il doit être nettoyé.
        _git("remote", "add", "origin", "https://me:ghp_LEAK@github.com/o/r.git", cwd=repo)
        bare = tmp_path / "bare.git"
        _git("init", "-q", "--bare", str(bare), cwd=tmp_path)
        steps = []
        try:
            core.git_push_advanced(repo, "https://github.com/o/r.git", ["main"], is_initial=True,
                                   token="ghp_SECRET", on_step=lambda c, o: steps.append(c))
        except Exception:
            pass  # le push réseau échoue (pas d'accès) : seule la config nous intéresse
        config = (repo / ".git" / "config").read_text()
        assert "ghp_SECRET" not in config and "ghp_LEAK" not in config
        assert "https://github.com/o/r.git" in config
        assert not any("ghp_" in step for step in steps)

    def test_clone_refuses_existing_target(self, tmp_path):
        (tmp_path / "t").mkdir()
        with pytest.raises(FileExistsError):
            core.git_clone("https://github.com/a/b.git", tmp_path / "t")


class TestCloneLocal:
    def test_local_paths_are_not_an_accepted_clone_transport(self, tmp_path):
        # Un chemin local n'est pas un transport accepté (évite les surprises « ext:: » / « file: »).
        with pytest.raises(ValueError):
            core.git_clone(str(tmp_path / "bare.git"), tmp_path / "out")
