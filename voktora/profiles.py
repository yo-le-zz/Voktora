"""
profiles.py — Runtime Profiles Voktora
Profils d'exécution par projet : env vars, commande de lancement,
dossier de travail, scripts pre/post run.
"""

from __future__ import annotations

import json
import subprocess
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path

import core


@dataclass
class RunProfile:
    name:         str
    run_cmd:      str                   = ""
    work_dir:     str                   = ""      # relatif à la racine du projet
    env:          dict[str, str]        = field(default_factory=dict)
    pre_run:      list[str]             = field(default_factory=list)  # scripts / cmds
    post_run:     list[str]             = field(default_factory=list)
    default:      bool                  = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RunProfile":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ── Stockage (par projet) ─────────────────────────────────────────────────────

def _profiles_path(project_path: Path) -> Path:
    return core.get_data_dir() / "profiles" / (
        project_path.name + ".json"
    )


def load_profiles(project_path: Path) -> list[RunProfile]:
    p = _profiles_path(project_path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return [RunProfile.from_dict(d) for d in data]
    except Exception:
        return []


def save_profiles(project_path: Path, profiles: list[RunProfile]) -> None:
    p = _profiles_path(project_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps([pr.to_dict() for pr in profiles], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def get_default_profile(project_path: Path) -> RunProfile | None:
    profiles = load_profiles(project_path)
    for pr in profiles:
        if pr.default:
            return pr
    return profiles[0] if profiles else None


def add_profile(project_path: Path, profile: RunProfile) -> None:
    profiles = load_profiles(project_path)
    profiles.append(profile)
    save_profiles(project_path, profiles)


def delete_profile(project_path: Path, name: str) -> None:
    profiles = [p for p in load_profiles(project_path) if p.name != name]
    save_profiles(project_path, profiles)


# ── Exécution ─────────────────────────────────────────────────────────────────

def launch(project_path: Path, profile: RunProfile,
           log_cb=None) -> subprocess.Popen | None:
    """
    Lance le profil dans un processus séparé.
    Retourne le Popen pour que l'UI puisse suivre ou tuer le process.
    """
    if not profile.run_cmd:
        return None

    work_dir = project_path / profile.work_dir if profile.work_dir else project_path
    env = {**os.environ, **profile.env}
    env["MERIDIAN_PROJECT_PATH"] = str(project_path)
    env["MERIDIAN_PROFILE"]      = profile.name

    import subprocess as _sp
    import sys as _sys

    # Exécuter scripts pre_run
    for cmd in profile.pre_run:
        try:
            r = _sp.run(cmd, shell=True, cwd=str(work_dir), env=env,
                        capture_output=True, text=True, timeout=30)
            if log_cb and r.stdout.strip():
                log_cb(f"[pre_run] {r.stdout.strip()}")
        except Exception as e:
            if log_cb:
                log_cb(f"[pre_run error] {e}")

    # Lancer la commande principale
    try:
        proc = _sp.Popen(
            profile.run_cmd, shell=True,
            cwd=str(work_dir), env=env,
            stdout=_sp.PIPE, stderr=_sp.STDOUT, text=True,
        )
        return proc
    except Exception as e:
        if log_cb:
            log_cb(f"[launch error] {e}")
        return None
