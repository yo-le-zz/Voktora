"""Compatibilité Linux : distributions, bureaux, Wayland/X11, terminaux, gestionnaires de fichiers."""

from __future__ import annotations

from pathlib import Path

import linux_env as le
import pytest

FEDORA = 'NAME="Fedora Linux"\nVERSION_ID=43\nID=fedora\nPRETTY_NAME="Fedora Linux 43 (Workstation Edition)"\n'
MINT = 'NAME="Linux Mint"\nID=linuxmint\nID_LIKE="ubuntu debian"\nVERSION_ID="22"\n'
ENDEAVOUR = 'ID=endeavouros\nID_LIKE=arch\n'
NIXOS = 'ID=nixos\nPRETTY_NAME="NixOS 25.05"\n'


@pytest.mark.parametrize("text,family", [(FEDORA, "fedora"), (MINT, "debian"), (ENDEAVOUR, "arch"),
                                         (NIXOS, "nixos"), ("ID=plan9\n", "other")])
def test_distro_family(text, family):
    assert le.detect_distro(lambda _p: text)["family"] == family


def test_distro_details_and_missing_file():
    info = le.detect_distro(lambda _p: FEDORA)
    assert info["name"].startswith("Fedora Linux 43") and info["version"] == "43"
    def boom(_p):
        raise FileNotFoundError
    assert le.detect_distro(boom) == {"id": "linux", "name": "Linux", "version": "", "family": "other"}


@pytest.mark.parametrize("env,expected", [
    ({"XDG_CURRENT_DESKTOP": "GNOME"}, "gnome"), ({"XDG_CURRENT_DESKTOP": "ubuntu:GNOME"}, "gnome"),
    ({"XDG_CURRENT_DESKTOP": "KDE"}, "kde"), ({"XDG_CURRENT_DESKTOP": "X-Cinnamon"}, "cinnamon"),
    ({"XDG_CURRENT_DESKTOP": "XFCE"}, "xfce"), ({"XDG_CURRENT_DESKTOP": "LXQt"}, "lxqt"),
    ({"XDG_CURRENT_DESKTOP": "Hyprland"}, "hyprland"), ({"DESKTOP_SESSION": "plasma"}, "kde"),
    ({"XDG_CURRENT_DESKTOP": "COSMIC"}, "cosmic"), ({}, "unknown"),
])
def test_desktop_detection(env, expected):
    assert le.detect_desktop(env) == expected


@pytest.mark.parametrize("env,expected", [
    ({"XDG_SESSION_TYPE": "wayland"}, "wayland"), ({"XDG_SESSION_TYPE": "x11"}, "x11"),
    ({"WAYLAND_DISPLAY": "wayland-0"}, "wayland"), ({"DISPLAY": ":0"}, "x11"), ({}, "none"),
])
def test_session_detection(env, expected):
    assert le.detect_session(env) == expected


def test_prepare_environment_respects_user_choice_and_session(monkeypatch):
    monkeypatch.setattr(le, "IS_LINUX", True)
    env = {"XDG_SESSION_TYPE": "wayland"}
    assert le.prepare_environment(env) == {"QT_QPA_PLATFORM": "wayland;xcb"} and env["QT_QPA_PLATFORM"] == "wayland;xcb"
    env = {"XDG_SESSION_TYPE": "x11"}
    assert le.prepare_environment(env)["QT_QPA_PLATFORM"] == "xcb;wayland"
    env = {"XDG_SESSION_TYPE": "wayland", "QT_QPA_PLATFORM": "offscreen"}
    assert le.prepare_environment(env) == {} and env["QT_QPA_PLATFORM"] == "offscreen"
    assert le.prepare_environment({}) == {}                  # pas d'affichage : on ne devine rien


def test_terminals_prefer_user_then_desktop_terminal():
    path = Path("/p/it's here")
    cmds = le.terminal_commands(path, {"XDG_CURRENT_DESKTOP": "KDE", "TERMINAL": "kitty"})
    assert cmds[0] == (["kitty", "--directory", str(path)], None)
    assert cmds[1][0] == ["xdg-terminal-exec"]
    assert cmds[2] == (["konsole", "--workdir", str(path)], None)
    gnome = le.terminal_commands(path, {"XDG_CURRENT_DESKTOP": "GNOME"})
    assert gnome[1][0] == ["ptyxis"] and gnome[1][1] == str(path)       # Fedora : Ptyxis, dossier via cwd


def test_terminal_commands_never_use_a_shell():
    for cmd, _cwd in le.terminal_commands(Path("/p/$(rm -rf ~)"), {"XDG_CURRENT_DESKTOP": "XFCE"}):
        assert "-c" not in cmd and "-e" not in cmd and not any(a.startswith("cd ") for a in cmd)


def test_file_managers_start_with_freedesktop_standard_then_desktop_choice():
    cmds = le.file_manager_commands(Path("/x"), {"XDG_CURRENT_DESKTOP": "XFCE"})
    assert cmds[0][0] == "xdg-open" and cmds[1][:2] == ["gio", "open"] and cmds[2][0] == "thunar"
    assert [c[0] for c in cmds].count("nautilus") == 1


def test_install_hint_is_distro_specific():
    assert "dnf" in le.install_hint("fedora") and "apt" in le.install_hint("debian")
    assert "xcb-cursor" in le.install_hint("other")


def test_missing_libs_reports_nothing_off_linux(monkeypatch):
    monkeypatch.setattr(le, "IS_LINUX", False)
    assert le.missing_system_libs({}) == []
