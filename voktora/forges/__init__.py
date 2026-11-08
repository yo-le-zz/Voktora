"""Voktora — forges : GitHub, GitLab, Forgejo (Fedora Forge, Codeberg…) et distinction des forks."""

from .accounts import add_account, client_for, list_accounts, remove_account
from .base import KINDS, PRESETS, ForgeError, Remote, Repo, guess_kind, parse_remote
from .clients import make_client
from .hub import ProjectForgeInfo, all_repos, confirm_with_api, git_remotes, project_info

__all__ = ["KINDS", "PRESETS", "ForgeError", "ProjectForgeInfo", "Remote", "Repo", "add_account", "all_repos",
           "client_for", "confirm_with_api", "git_remotes", "guess_kind", "list_accounts", "make_client",
           "parse_remote", "project_info", "remove_account"]
