"""Détection des environnements de développement (versions des outils, fichiers de projet, venv). Ne lit jamais les valeurs des .env."""

from __future__ import annotations

from pathlib import Path

TOOLS = [("Python", ["python3", "--version"]), ("Node.js", ["node", "--version"]), ("npm", ["npm", "--version"]),
         ("Rust (cargo)", ["cargo", "--version"]), ("Go", ["go", "version"]), ("Git", ["git", "--version"]),
         ("Docker", ["docker", "--version"]), ("SSH", ["ssh", "-V"])]
MARKERS = {"pyproject.toml": "Python (pyproject)", "requirements.txt": "Python (requirements)", "package.json": "Node.js",
           "Cargo.toml": "Rust", "go.mod": "Go", "Dockerfile": "Docker", "docker-compose.yml": "Docker Compose",
           "compose.yaml": "Docker Compose", "Makefile": "Make", "uv.lock": "uv", "poetry.lock": "Poetry"}


def tool_versions(runner) -> list[dict]:
    rows = []
    for name, args in TOOLS:
        res = runner(args, timeout=10)
        first = (res.out or res.error or "").strip().splitlines()
        rows.append({"tool": name, "ok": res.ok or (name == "SSH" and bool(first) and "OpenSSH" in first[0]),
                     "version": first[0] if first else "introuvable"})
    return rows


def project_environment(project: str | Path) -> dict:
    root = Path(project)
    found = [label for f, label in MARKERS.items() if (root / f).exists()]
    venvs = [d.name for d in root.iterdir() if d.is_dir() and (d / "pyvenv.cfg").exists()] if root.is_dir() else []
    env_files = sorted(p.name for p in root.glob(".env*") if p.is_file()) if root.is_dir() else []
    return {"markers": found, "venvs": venvs, "env_files": env_files,
            "node_modules": (root / "node_modules").is_dir(), "git": (root / ".git").exists()}
