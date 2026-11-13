"""Fichiers de configuration : dépendances déclarées, points d'entrée, maturin/PyO3, crates, scripts.
Sortie dans FileResult.info : dependencies=[{name, spec, ecosystem, dev, line}], entries, maturin, cargo, scripts."""

from __future__ import annotations

import json
import re
import tomllib

from ..core.model import FileResult, Issue
from .base import Analyzer, register


def _py_req(line: str) -> tuple[str, str] | None:
    line = line.split("#")[0].strip()
    if not line or line.startswith(("-", "git+", "http")):
        return None
    m = re.match(r"([A-Za-z0-9_.\-]+)\s*(?:\[[^\]]*\])?\s*(.*)", line)
    return (m.group(1), m.group(2).split(";")[0].strip()) if m else None


def _find_line(text: str, needle: str) -> int:
    for i, ln in enumerate(text.splitlines(), 1):
        if needle in ln:
            return i
    return 1


class ConfigAnalyzer(Analyzer):
    lang = "config"
    filenames = ("pyproject.toml", "package.json", "cargo.toml", "cmakelists.txt", "setup.py", "setup.cfg", "dockerfile",
                 "makefile", "go.mod")
    patterns = (r"requirements[\w.\-]*\.txt",)

    def analyze_file(self, path: str, text: str) -> FileResult:
        name = path.rsplit("/", 1)[-1].lower()
        result = FileResult(path, "config", loc=len([ln for ln in text.splitlines() if ln.strip()]))
        deps: list[dict] = result.info.setdefault("dependencies", [])
        try:
            if name == "pyproject.toml":
                self._pyproject(text, result, deps)
            elif name == "package.json":
                self._package_json(text, result, deps)
            elif name == "cargo.toml":
                self._cargo(text, result, deps)
            elif name.startswith("requirements"):
                for i, ln in enumerate(text.splitlines(), 1):
                    req = _py_req(ln)
                    if req:
                        deps.append({"name": req[0], "spec": req[1], "ecosystem": "pypi", "dev": "dev" in name or "test" in name,
                                     "line": i})
            elif name == "cmakelists.txt":
                for m in re.finditer(r"find_package\(\s*(\w+)", text, re.IGNORECASE):
                    deps.append({"name": m.group(1), "spec": "", "ecosystem": "cmake", "dev": False,
                                 "line": text.count("\n", 0, m.start()) + 1})
                for m in re.finditer(r"add_executable\(\s*(\w+)", text, re.IGNORECASE):
                    result.info.setdefault("entries", []).append({"kind": "executable", "name": m.group(1)})
            elif name == "setup.py":
                for m in re.finditer(r"['\"]([\w.\-]+)\s*(?:[<>=!~]=?[^'\"]*)?['\"]", text[text.find("install_requires"):][:2000]
                                     if "install_requires" in text else ""):
                    deps.append({"name": m.group(1), "spec": "", "ecosystem": "pypi", "dev": False,
                                 "line": _find_line(text, m.group(1))})
            elif name == "go.mod":
                for m in re.finditer(r"^\s*([\w./\-]+)\s+(v[\w.\-+]+)", text, re.MULTILINE):
                    deps.append({"name": m.group(1), "spec": m.group(2), "ecosystem": "go", "dev": False,
                                 "line": text.count("\n", 0, m.start()) + 1})
            elif name == "dockerfile":
                for m in re.finditer(r"^\s*(?:CMD|ENTRYPOINT)\s+(.+)$", text, re.MULTILINE | re.IGNORECASE):
                    result.info.setdefault("entries", []).append({"kind": "docker", "name": m.group(1).strip()[:80]})
        except (ValueError, tomllib.TOMLDecodeError, KeyError, TypeError) as exc:
            result.issues.append(Issue(path, 1, "warn", "CONFIG-PARSE", f"Fichier de configuration illisible : {exc}",
                                       "Les dépendances de ce fichier n'ont pas pu être analysées.", "Corrigez la syntaxe."))
        return result

    def _pyproject(self, text, result, deps):
        data = tomllib.loads(text)
        proj = data.get("project", {})
        for spec in proj.get("dependencies", []):
            req = _py_req(spec)
            if req:
                deps.append({"name": req[0], "spec": req[1], "ecosystem": "pypi", "dev": False, "line": _find_line(text, req[0])})
        for group, items in {**proj.get("optional-dependencies", {}), **data.get("dependency-groups", {})}.items():
            for spec in items:
                req = _py_req(spec) if isinstance(spec, str) else None
                if req:
                    deps.append({"name": req[0], "spec": req[1], "ecosystem": "pypi", "dev": True, "line": _find_line(text, req[0]),
                                 "group": group})
        for script, target in proj.get("scripts", {}).items():
            result.info.setdefault("entries", []).append({"kind": "console_script", "name": script, "target": str(target)})
        tool = data.get("tool", {})
        if "maturin" in tool:
            mt = tool["maturin"]
            result.info["maturin"] = {"module_name": mt.get("module-name", ""), "manifest_path": mt.get("manifest-path", "Cargo.toml"),
                                      "python_source": mt.get("python-source", ""), "bindings": mt.get("bindings", "pyo3")}
        if proj.get("name"):
            result.info["project_name"] = proj["name"]
        if "setuptools" in tool or data.get("build-system", {}).get("build-backend", "").startswith("setuptools"):
            result.info["build_backend"] = "setuptools"
        if data.get("build-system", {}).get("build-backend", "").startswith("maturin"):
            result.info["build_backend"] = "maturin"

    def _package_json(self, text, result, deps):
        data = json.loads(text)
        for key, dev in (("dependencies", False), ("devDependencies", True), ("peerDependencies", False)):
            for dep, spec in (data.get(key) or {}).items():
                deps.append({"name": dep, "spec": str(spec), "ecosystem": "npm", "dev": dev, "line": _find_line(text, f'"{dep}"')})
        entries = result.info.setdefault("entries", [])
        if data.get("main"):
            entries.append({"kind": "main", "name": "main", "target": data["main"]})
        for k, v in (data.get("bin") or ({data.get("name", "bin"): data["bin"]} if isinstance(data.get("bin"), str) else {})).items():
            entries.append({"kind": "bin", "name": k, "target": v})
        for k, v in (data.get("scripts") or {}).items():
            result.info.setdefault("scripts", {})[k] = v

    def _cargo(self, text, result, deps):
        data = tomllib.loads(text)
        pkg = data.get("package", {})
        for key, dev in (("dependencies", False), ("dev-dependencies", True), ("build-dependencies", True)):
            for dep, spec in (data.get(key) or {}).items():
                version = spec if isinstance(spec, str) else spec.get("version", "") if isinstance(spec, dict) else ""
                path = spec.get("path", "") if isinstance(spec, dict) else ""
                deps.append({"name": dep, "spec": version, "ecosystem": "crates", "dev": dev, "line": _find_line(text, dep),
                             "path": path, "package": spec.get("package", "") if isinstance(spec, dict) else ""})
        lib = data.get("lib", {})
        result.info["cargo"] = {"package": pkg.get("name", ""), "version": pkg.get("version", ""),
                                "lib_name": lib.get("name", pkg.get("name", "").replace("-", "_")),
                                "crate_type": lib.get("crate-type", []), "bins": [b.get("name") for b in data.get("bin", [])],
                                "workspace": data.get("workspace", {}).get("members", []),
                                "pyo3": any(d["name"] == "pyo3" for d in deps)}
        for b in data.get("bin", []):
            result.info.setdefault("entries", []).append({"kind": "bin", "name": b.get("name", ""), "target": b.get("path", "")})


register(ConfigAnalyzer())
