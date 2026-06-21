"""
templates.py — Templates de projets Voktora
Version : 1.0.1
Crée la structure initiale d'un projet avec git init, dépendances, README.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import core

BUILTIN_TEMPLATES: dict[str, dict] = {
    "python": {
        "label": "🐍  Python",
        "desc":  "Projet Python avec venv + uv, src/, tests/, README, .gitignore",
        "files": {
            "src/__init__.py": "",
            "src/main.py":     'if __name__ == "__main__":\n    print("Hello, Voktora!")\n',
            "tests/__init__.py": "",
            "tests/test_main.py": "def test_placeholder():\n    assert True\n",
            ".gitignore":      "__pycache__/\n*.pyc\n.venv/\ndist/\n*.egg-info/\n",
            "README.md":       "# {name}\n\nCreated with Voktora.\n",
            "pyproject.toml":  '[project]\nname = "{name}"\nversion = "0.1.0"\nrequires-python = ">=3.11"\n',
        },
        "post_cmds": ["uv venv", "git init", "git add .", 'git commit -m "init: Voktora template"'],
    },
    "cpp": {
        "label": "⚡  C++",
        "desc":  "Projet C++ avec CMakeLists, src/, include/, .gitignore",
        "files": {
            "src/main.cpp":    '#include <iostream>\nint main() {\n    std::cout << "Hello, Voktora!\\n";\n    return 0;\n}\n',
            "include/.keep":   "",
            "CMakeLists.txt":  'cmake_minimum_required(VERSION 3.20)\nproject({name})\nset(CMAKE_CXX_STANDARD 17)\nadd_executable({name} src/main.cpp)\n',
            ".gitignore":      "build/\n*.o\n*.a\n*.so\n*.exe\n",
            "README.md":       "# {name}\n\nCreated with Voktora.\n",
        },
        "post_cmds": ["git init", "git add .", 'git commit -m "init: Voktora template"'],
    },
    "web": {
        "label": "🌐  Web App",
        "desc":  "HTML + CSS + JS, structure de base",
        "files": {
            "index.html": "<!DOCTYPE html>\n<html lang='fr'>\n<head>\n  <meta charset='UTF-8'/>\n  <title>{name}</title>\n  <link rel='stylesheet' href='style.css'/>\n</head>\n<body>\n  <h1>{name}</h1>\n  <script src='main.js'></script>\n</body>\n</html>\n",
            "style.css":  "* { box-sizing: border-box; margin: 0; padding: 0; }\nbody { font-family: sans-serif; }\n",
            "main.js":    "console.log('Hello, {name}!');\n",
            ".gitignore": "node_modules/\n.env\n",
            "README.md":  "# {name}\n\nCreated with Voktora.\n",
        },
        "post_cmds": ["git init", "git add .", 'git commit -m "init: Voktora template"'],
    },
    "discord_bot": {
        "label": "🤖  Discord Bot",
        "desc":  "Bot Discord Python avec discord.py, .env, structure de base",
        "files": {
            "bot.py": 'import discord\nfrom discord.ext import commands\nimport os\nfrom dotenv import load_dotenv\n\nload_dotenv()\nbot = commands.Bot(command_prefix="!", intents=discord.Intents.default())\n\n@bot.event\nasync def on_ready():\n    print(f"Logged in as {bot.user}")\n\nbot.run(os.getenv("DISCORD_TOKEN"))\n',
            ".env":          "DISCORD_TOKEN=your_token_here\n",
            ".env.example":  "DISCORD_TOKEN=\n",
            ".gitignore":    "__pycache__/\n*.pyc\n.venv/\n.env\n",
            "requirements.txt": "discord.py\npython-dotenv\n",
            "README.md":     "# {name}\n\nBot Discord créé avec Voktora.\n",
        },
        "post_cmds": ["uv venv", "git init", "git add .", 'git commit -m "init: Voktora template"'],
    },
    "minecraft_mod": {
        "label": "🧱  Minecraft Mod",
        "desc":  "Mod Minecraft Java avec Gradle + Fabric, structure de base",
        "files": {
            "src/main/java/mod/Main.java": 'package mod;\nimport net.fabricmc.api.ModInitializer;\npublic class Main implements ModInitializer {\n    @Override\n    public void onInitialize() {\n        System.out.println("{name} initialized!");\n    }\n}\n',
            "src/main/resources/fabric.mod.json": '{{\n  "schemaVersion": 1,\n  "id": "{name_lower}",\n  "version": "1.0.0",\n  "name": "{name}",\n  "entrypoints": {{"main": ["mod.Main"]}}\n}}\n',
            "build.gradle": '// Fabric template\nplugins {{\n    id "fabric-loom" version "1.0-SNAPSHOT"\n}}\n',
            ".gitignore":   ".gradle/\nbuild/\n*.class\n",
            "README.md":    "# {name}\n\nMod Minecraft créé avec Voktora.\n",
        },
        "post_cmds": ["git init", "git add .", 'git commit -m "init: Voktora template"'],
    },
    "blank": {
        "label": "📄  Vide",
        "desc":  "Projet vide avec git init et README",
        "files": {
            "README.md":  "# {name}\n",
            ".gitignore": "",
        },
        "post_cmds": ["git init", "git add .", 'git commit -m "init: initial commit"'],
    },
}


def get_template_names() -> list[str]:
    return list(BUILTIN_TEMPLATES.keys())


def apply_template(template_key: str, project_path: Path,
                   log_cb: Callable[[str], None] | None = None) -> None:
    """
    Crée la structure du template dans `project_path` et exécute les post_cmds.
    """
    tpl = BUILTIN_TEMPLATES.get(template_key, BUILTIN_TEMPLATES["blank"])
    name       = project_path.name
    name_lower = name.lower().replace(" ", "_").replace("-", "_")

    ctx = {"name": name, "name_lower": name_lower}

    for rel_path, content in tpl["files"].items():
        target = project_path / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            formatted = content.format(**ctx)
        except KeyError:
            formatted = content
        target.write_text(formatted, encoding="utf-8")
        if log_cb:
            log_cb(f"  ✓ {rel_path}")

    for cmd in tpl.get("post_cmds", []):
        try:
            r = subprocess.run(
                cmd, shell=True, cwd=str(project_path),
                capture_output=True, text=True, timeout=60,
            )
            if log_cb:
                out = (r.stdout + r.stderr).strip()
                log_cb(f"  $ {cmd}" + (f"\n    {out}" if out else ""))
        except Exception as e:
            if log_cb:
                log_cb(f"  ✗ {cmd}: {e}")
