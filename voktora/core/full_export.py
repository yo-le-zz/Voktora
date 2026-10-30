"""
Voktora — core.full_export
Export complet (tous les projets + configuration) en trois phases bien séparées :

  1. PLANIFICATION  (`plan_full_export`)  : lecture seule. Recense les projets
     existants, calcule leur taille, attribue à chacun un préfixe unique dans
     l'archive et signale ceux dont le dossier a disparu. Rien n'est écrit.
  2. CONFIGURATION  (`public_config`)     : construit la copie « partageable »
     de la config, sans compte GitHub, sans coffre ni tokens de projet.
  3. COPIE          (`write_full_export`) : écrit l'archive dans un fichier
     temporaire puis le renomme. Chaque projet est copié isolément : un projet
     illisible n'empêche pas l'export des autres, et tout ce qui a été ignoré
     est consigné dans `export_info.txt` et dans le rapport retourné.

Seule l'annulation (OperationCancelled) interrompt tout l'export.
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import archive, config_store, constants, paths

_MAX_LISTED_SKIPPED = 50   # lignes de fichiers ignorés détaillées par projet dans export_info.txt


@dataclass(frozen=True)
class ProjectSource:
    name: str
    folder: Path
    archive_prefix: str     # « projects/<nom> », unique dans l'archive
    file_count: int
    total_bytes: int


@dataclass(frozen=True)
class ExportPlan:
    sources: tuple[ProjectSource, ...]
    missing: tuple[str, ...]            # projets enregistrés dont le dossier n'existe plus

    @property
    def total_bytes(self) -> int:
        return sum(s.total_bytes for s in self.sources)


@dataclass
class ExportReport:
    archive_path: Path
    exported: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)       # (projet, raison)
    skipped_files: dict[str, list[str]] = field(default_factory=dict)  # projet -> fichiers ignorés

    @property
    def has_warnings(self) -> bool:
        return bool(self.failed or self.skipped_files)


# ──────────────────────────────────────────────
# PHASE 1 — PLANIFICATION
# ──────────────────────────────────────────────

def plan_full_export(cfg: dict) -> ExportPlan:
    """Recense les projets à exporter (aucune écriture)."""
    sources: list[ProjectSource] = []
    missing: list[str] = []
    used: set[str] = set()
    for entry in cfg.get("projects", []):
        raw_path = entry.get("path")
        if not raw_path:
            continue
        folder = Path(raw_path)
        label = entry.get("name") or folder.name
        if not folder.is_dir():
            missing.append(label)
            continue
        # Deux projets de même nom (dossiers différents) ne doivent pas se mélanger.
        prefix, n = f"projects/{folder.name}", 2
        while prefix in used:
            prefix, n = f"projects/{folder.name}_{n}", n + 1
        used.add(prefix)
        count, total = archive._tree_size(folder)
        sources.append(ProjectSource(label, folder, prefix, count, total))
    return ExportPlan(tuple(sources), tuple(missing))


# ──────────────────────────────────────────────
# PHASE 2 — CONFIGURATION PUBLIQUE
# ──────────────────────────────────────────────

def public_config(cfg: dict) -> dict:
    """Copie de la config sans aucun secret : l'archive peut être partagée."""
    public = {k: v for k, v in cfg.items() if k not in ("github_account", "vault")}
    public["projects"] = [
        {**e, "github_token": "", "github_token_protected": False} for e in cfg.get("projects", [])
    ]
    return public


def _info_text(timestamp: str, plan: ExportPlan, report: ExportReport) -> str:
    lines = [f"Voktora export — {timestamp}", f"Version : {constants.APP_VERSION}", ""]
    lines.append(f"Projets exportés ({len(report.exported)}) :")
    lines += [f"  - {name}" for name in report.exported] or ["  (aucun)"]
    if plan.missing:
        lines += ["", f"Projets introuvables, non exportés ({len(plan.missing)}) :"]
        lines += [f"  - {name}" for name in plan.missing]
    if report.failed:
        lines += ["", f"Projets en échec ({len(report.failed)}) :"]
        lines += [f"  - {name} : {reason}" for name, reason in report.failed]
    for name, files in report.skipped_files.items():
        lines += ["", f"Fichiers ignorés dans « {name} » (verrouillés ou disparus) : {len(files)}"]
        lines += [f"  - {rel}" for rel in files[:_MAX_LISTED_SKIPPED]]
        if len(files) > _MAX_LISTED_SKIPPED:
            lines.append(f"  … et {len(files) - _MAX_LISTED_SKIPPED} autre(s)")
    return "\n".join(lines) + "\n"


# ──────────────────────────────────────────────
# PHASE 3 — COPIE
# ──────────────────────────────────────────────

def write_full_export(plan: ExportPlan, cfg: dict, output_dir: Path | None = None,
                      on_progress: archive.ProgressCallback | None = None,
                      cancel: archive.CancelCheck | None = None) -> ExportReport:
    """Écrit l'archive complète et retourne un rapport détaillé."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    tracker = archive.ProgressTracker(plan.total_bytes, on_progress)
    public = public_config(cfg)
    report = ExportReport(archive_path=Path())

    def _write(zf: zipfile.ZipFile) -> None:
        for source in plan.sources:
            archive._check_cancel(cancel)
            try:
                skipped = archive.add_tree_to_zip(zf, source.folder, source.archive_prefix, tracker, cancel)
            except constants.OperationCancelled:
                raise
            except Exception as exc:   # un projet défaillant ne doit pas faire perdre tous les autres
                report.failed.append((source.name, str(exc) or exc.__class__.__name__))
                continue
            report.exported.append(source.name)
            if skipped:
                report.skipped_files[source.name] = skipped
        zf.writestr("config.json", json.dumps(public, indent=2, ensure_ascii=False))
        zf.writestr("export_info.txt", _info_text(timestamp, plan, report))

    target_dir = Path(output_dir) if output_dir else paths.get_backups_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    report.archive_path = archive.write_zip_atomically(target_dir / f"voktora_export_{timestamp}.zip", _write)
    tracker.finish(report.archive_path.name)
    return report


def export_everything(on_progress: archive.ProgressCallback | None = None,
                      cancel: archive.CancelCheck | None = None,
                      output_dir: Path | None = None) -> ExportReport:
    """Enchaîne les trois phases à partir de la configuration courante."""
    cfg = config_store._load_config()
    plan = plan_full_export(cfg)
    return write_full_export(plan, cfg, output_dir, on_progress, cancel)
