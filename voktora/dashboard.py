"""
dashboard.py — Health & Usage Analytics local Voktora
Analyse l'état des projets : repos cassés, branches en retard,
.gitignore manquant, inactivité, stats d'usage.
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import core


# ── Types ──────────────────────────────────────────────────────────────────────

@dataclass
class ProjectHealth:
    path:          Path
    name:          str
    issues:        list[str] = field(default_factory=list)
    warnings:      list[str] = field(default_factory=list)
    info:          list[str] = field(default_factory=list)
    last_opened:   str = ""
    commit_count:  int = 0
    ahead_behind:  tuple[int, int] = (0, 0)  # (ahead, behind)

    @property
    def score(self) -> int:
        """Score de santé : 100 = parfait, 0 = très mauvais."""
        s = 100
        s -= len(self.issues)   * 20
        s -= len(self.warnings) * 5
        return max(0, min(100, s))

    @property
    def status_icon(self) -> str:
        s = self.score
        if s >= 80: return "🟢"
        if s >= 50: return "🟡"
        return "🔴"


@dataclass
class DashboardReport:
    generated_at:   str
    total_projects: int
    health:         list[ProjectHealth] = field(default_factory=list)
    usage_stats:    dict[str, Any]      = field(default_factory=dict)


# ── Usage tracking ─────────────────────────────────────────────────────────────

def _usage_path() -> Path:
    return core.get_data_dir() / "usage.json"


def load_usage() -> dict:
    p = _usage_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def record_open(project_path: Path) -> None:
    """Enregistre une ouverture de projet (appelé par ui_main)."""
    usage = load_usage()
    key   = str(project_path)
    entry = usage.setdefault(key, {"opens": 0, "first_open": "", "last_open": ""})
    now   = datetime.now().isoformat()
    entry["opens"] += 1
    if not entry["first_open"]:
        entry["first_open"] = now
    entry["last_open"] = now
    p = _usage_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(usage, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Analyse ────────────────────────────────────────────────────────────────────

def analyze_project(project_path: Path) -> ProjectHealth:
    h = ProjectHealth(path=project_path, name=project_path.name)
    usage = load_usage().get(str(project_path), {})
    h.last_opened = usage.get("last_open", "jamais")

    # ── Existence du dossier ──
    if not project_path.exists():
        h.issues.append("❌ Dossier introuvable (projet cassé)")
        return h

    # ── Git ──
    git_dir = project_path / ".git"
    if not git_dir.exists():
        h.warnings.append("⚠️  Pas de dépôt Git initialisé")
    else:
        # .gitignore
        gitignore = project_path / ".gitignore"
        if not gitignore.exists():
            h.warnings.append("⚠️  .gitignore manquant (fichiers sensibles non protégés)")

        # Ahead / Behind
        try:
            r = subprocess.run(
                ["git", "rev-list", "--left-right", "--count", "HEAD...@{upstream}"],
                cwd=str(project_path), capture_output=True, text=True, timeout=8,
            )
            if r.returncode == 0 and r.stdout.strip():
                a, b = r.stdout.strip().split()
                h.ahead_behind = (int(a), int(b))
                if int(b) > 0:
                    h.warnings.append(f"⚠️  {b} commit(s) en retard sur la branche distante")
                if int(a) > 5:
                    h.warnings.append(f"⚠️  {a} commits locaux non poussés")
        except Exception:
            pass

        # Branches non mergées
        try:
            r = subprocess.run(
                ["git", "branch", "--no-merged", "HEAD"],
                cwd=str(project_path), capture_output=True, text=True, timeout=8,
            )
            if r.returncode == 0:
                branches = [b.strip().lstrip("* ") for b in r.stdout.strip().splitlines() if b.strip()]
                if branches:
                    h.warnings.append(f"⚠️  Branches non mergées : {', '.join(branches[:3])}")
        except Exception:
            pass

        # Nombre de commits
        try:
            r = subprocess.run(
                ["git", "rev-list", "--count", "HEAD"],
                cwd=str(project_path), capture_output=True, text=True, timeout=8,
            )
            if r.returncode == 0:
                h.commit_count = int(r.stdout.strip())
        except Exception:
            pass

    # ── Inactivité ──
    if h.last_opened and h.last_opened != "jamais":
        try:
            last = datetime.fromisoformat(h.last_opened)
            if datetime.now() - last > timedelta(days=90):
                h.info.append(f"ℹ️  Projet inactif depuis {(datetime.now() - last).days} jours")
        except Exception:
            pass

    # ── Info positive ──
    if not h.issues and not h.warnings:
        h.info.append("✅ Projet en bonne santé")

    return h


def generate_report(paths: list[Path] | None = None) -> DashboardReport:
    """
    Génère un rapport complet.
    Si `paths` est None, analyse toutes les instances et intents connus.
    """
    if paths is None:
        cfg    = core._load_config()
        all_p  = cfg.get("instances", []) + cfg.get("intents", [])
        paths  = [Path(e["path"]) for e in all_p]

    health     = [analyze_project(p) for p in paths]
    usage      = load_usage()
    total_opens = sum(v.get("opens", 0) for v in usage.values())
    most_used  = sorted(usage.items(), key=lambda x: x[1].get("opens", 0), reverse=True)[:5]

    report = DashboardReport(
        generated_at   = datetime.now().strftime("%Y-%m-%d %H:%M"),
        total_projects = len(paths),
        health         = health,
        usage_stats    = {
            "total_opens":    total_opens,
            "most_used":      [(Path(k).name, v.get("opens", 0)) for k, v in most_used],
            "broken_count":   sum(1 for h in health if h.score < 50),
            "healthy_count":  sum(1 for h in health if h.score >= 80),
        },
    )
    return report
