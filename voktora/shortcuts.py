"""
Voktora — shortcuts (1.1.4) : raccourcis clavier personnalisables, avec import/export JSON validés.
Registre d'actions connues (identifiant → libellé, raccourci par défaut) ; les surcharges de l'utilisateur sont dans la config
(« shortcuts »). Un fichier importé est validé : identifiants connus seulement, séquences Qt valides, pas de doublon.
"""

from __future__ import annotations

import json

import core

DEFAULTS: dict[str, tuple[str, str]] = {
    "refresh": ("Actualiser la liste", "F5"),
    "new_project": ("Nouveau projet", "Ctrl+N"),
    "import": ("Importer un dossier ou un ZIP", "Ctrl+I"),
    "switch_project": ("Aller à un projet", "Ctrl+F"),
    "clear_search": ("Effacer la recherche", "Escape"),
    "ai_chat": ("Assistant IA", "Ctrl+Shift+A"),
    "palette": ("Palette de commandes", "Ctrl+K"),
    "plugins": ("Plugins et marketplace", "Ctrl+Shift+P"),
}
_registry: dict[str, object] = {}              # id → QShortcut | QAction


class ShortcutError(ValueError):
    pass


def overrides() -> dict[str, str]:
    cfg = core.get_app_config().get("shortcuts")
    return {k: v for k, v in (cfg.items() if isinstance(cfg, dict) else []) if k in DEFAULTS and isinstance(v, str)}


def effective() -> dict[str, str]:
    over = overrides()
    return {i: over.get(i, d[1]) for i, d in DEFAULTS.items()}


def valid_sequence(text: str) -> bool:
    if text == "":
        return True                                            # raccourci retiré
    from PySide6.QtGui import QKeySequence
    seq = QKeySequence(text)
    return not seq.isEmpty() and seq.count() == 1 and seq.toString() != ""


def conflicts(mapping: dict[str, str]) -> dict[str, list[str]]:
    seen: dict[str, list[str]] = {}
    for i, seq in mapping.items():
        if seq:
            seen.setdefault(seq.casefold(), []).append(i)
    return {k: v for k, v in seen.items() if len(v) > 1}


def set_shortcuts(mapping: dict[str, str]) -> None:
    """Enregistre (en ne gardant que ce qui diffère du défaut) après validation."""
    clean = {}
    for i, seq in mapping.items():
        if i not in DEFAULTS:
            raise ShortcutError(f"Action inconnue : {i}")
        if not valid_sequence(seq):
            raise ShortcutError(f"Raccourci invalide pour « {DEFAULTS[i][0]} » : {seq}")
        if seq != DEFAULTS[i][1]:
            clean[i] = seq
    full = {i: clean.get(i, DEFAULTS[i][1]) for i in DEFAULTS}
    dup = conflicts(full)
    if dup:
        raise ShortcutError("Raccourcis en double : " + " ; ".join(f"{k} → {', '.join(DEFAULTS[i][0] for i in v)}" for k, v in dup.items()))
    cfg = core.get_app_config()
    cfg["shortcuts"] = clean
    core.set_app_config(cfg)
    apply()


def export_text() -> str:
    return json.dumps({"voktora_shortcuts": 1, "shortcuts": effective()}, indent=2, ensure_ascii=False)


def import_text(text: str) -> dict[str, str]:
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ShortcutError(f"JSON invalide : {exc}") from exc
    if not isinstance(data, dict) or data.get("voktora_shortcuts") != 1 or not isinstance(data.get("shortcuts"), dict):
        raise ShortcutError("Ce fichier n'est pas un export de raccourcis Voktora.")
    incoming = {k: v for k, v in data["shortcuts"].items() if isinstance(k, str)}
    unknown = [k for k in incoming if k not in DEFAULTS]
    if unknown:
        raise ShortcutError("Actions inconnues ignorées refusées : " + ", ".join(unknown[:5]))
    if not all(isinstance(v, str) for v in incoming.values()):
        raise ShortcutError("Valeurs invalides.")
    merged = {**effective(), **incoming}
    set_shortcuts(merged)
    return merged


def register(identifier: str, obj) -> None:
    """Associe une action de l'application à son identifiant (QShortcut ou QAction) et applique le raccourci voulu."""
    _registry[identifier] = obj
    _apply_one(identifier)


def _apply_one(identifier: str) -> None:
    obj = _registry.get(identifier)
    if obj is None:
        return
    from PySide6.QtGui import QKeySequence
    try:
        seq = QKeySequence(effective()[identifier])
        (obj.setKey if hasattr(obj, "setKey") else obj.setShortcut)(seq)
    except RuntimeError:                                        # objet Qt détruit
        _registry.pop(identifier, None)


def apply() -> None:
    for identifier in list(_registry):
        _apply_one(identifier)
