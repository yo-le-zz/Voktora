"""
Voktora — plugins.deps (1.1.1)
Dépendances ENTRE plugins : ordre de chargement, versions exigées, plugins qui en dépendent.

`plugin.json` : `"dependencies": {"api-plus": ">=1.0.0", "autre-plugin": "^2.1"}`.
Un plugin n'est chargé que si toutes ses dépendances sont installées, actives, chargées sans erreur et dans la bonne
version ; elles sont chargées AVANT lui. Un plugin lit ce que son parent expose avec `api.plugin("api-plus")`
(le parent publie un objet avec `api.provide(objet)`).
Ce module ne dépend d'aucun Qt ni d'aucun accès réseau : la résolution est de la pure logique, facile à tester.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from . import manifest as manifest_mod


@dataclass
class Resolution:
    order: list[str] = field(default_factory=list)                  # identifiants, dépendances d'abord
    problems: dict[str, str] = field(default_factory=dict)         # plugin → pourquoi il ne peut pas être chargé


def check(plugin_id: str, wanted: Mapping[str, str], available: Mapping[str, str]) -> str:
    """Message d'erreur si une dépendance manque ou n'a pas la bonne version, sinon « »."""
    for dep, spec in wanted.items():
        if dep not in available:
            return (f"Dépendance manquante : « {dep} » ({spec}). Installez-la depuis le marketplace "
                    f"(Plugins → Marketplace).")
        if not manifest_mod.satisfies(available[dep], spec):
            return f"Dépendance « {dep} » en version {available[dep]}, mais {plugin_id} exige {spec}."
    return ""


def resolve(plugins: Mapping[str, Mapping[str, str]], versions: Mapping[str, str],
            disabled: Iterable[str] = ()) -> Resolution:
    """Ordre de chargement + problèmes.

    `plugins` : {id: {dépendance: spécification}} pour les plugins à charger ; `versions` : {id: version installée}.
    Un plugin désactivé, absent, en cycle ou dont une dépendance est en échec reçoit un problème (et ses dépendants aussi).
    """
    disabled = set(disabled)
    out = Resolution()
    state: dict[str, int] = {}            # 1 = en cours, 2 = terminé

    def visit(pid: str, chain: list[str]) -> None:
        if state.get(pid) == 2:
            return
        if state.get(pid) == 1:
            cycle = " → ".join([*chain[chain.index(pid):], pid])
            out.problems.setdefault(pid, f"Dépendances circulaires : {cycle}.")
            return
        state[pid] = 1
        wanted = plugins.get(pid, {})
        problem = check(pid, wanted, versions)
        for dep in wanted:
            if dep in versions:
                if dep in plugins:
                    visit(dep, [*chain, pid])
                if dep in disabled:
                    problem = problem or f"Dépendance « {dep} » désactivée : activez-la d'abord."
                elif dep in out.problems:
                    problem = problem or f"Dépendance « {dep} » indisponible : {out.problems[dep]}"
        if problem:
            out.problems.setdefault(pid, problem)
        if pid in out.problems:
            state[pid] = 2
            return
        state[pid] = 2
        out.order.append(pid)

    for pid in sorted(plugins):
        visit(pid, [])
    return out


def dependents(plugin_id: str, plugins: Mapping[str, Mapping[str, str]], transitive: bool = True) -> list[str]:
    """Plugins qui dépendent de `plugin_id` (directement, ou en chaîne), dans un ordre stable."""
    found: list[str] = []
    todo = [plugin_id]
    while todo:
        current = todo.pop()
        for pid, deps in sorted(plugins.items()):
            if current in deps and pid not in found and pid != plugin_id:
                found.append(pid)
                if transitive:
                    todo.append(pid)
    return found


def breaks_dependents(plugin_id: str, new_version: str, plugins: Mapping[str, Mapping[str, str]]) -> list[str]:
    """Plugins installés dont la plage de versions exigée n'accepterait PAS `new_version` de `plugin_id`."""
    return [pid for pid, deps in sorted(plugins.items())
            if plugin_id in deps and not manifest_mod.satisfies(new_version, deps[plugin_id])]


def missing_for_install(wanted: Mapping[str, str], installed: Mapping[str, str],
                        catalog: Mapping[str, tuple[str, Mapping[str, str]]]) -> tuple[list[str], list[str]]:
    """Quels plugins du marketplace installer pour satisfaire `wanted` ?

    `catalog` : {id: (version, {ses dépendances})}. Retourne (à installer dans l'ordre, problèmes lisibles)."""
    order: list[str] = []
    problems: list[str] = []
    seen: set[str] = set()

    def need(dep: str, spec: str, chain: tuple[str, ...]) -> None:
        if dep in chain:
            problems.append(f"Dépendances circulaires autour de « {dep} ».")
            return
        if dep in installed and manifest_mod.satisfies(installed[dep], spec):
            return
        if dep in seen:
            return
        entry = catalog.get(dep)
        if entry is None:
            problems.append(f"« {dep} » ({spec}) est introuvable dans le marketplace.")
            return
        version, sub = entry
        if not manifest_mod.satisfies(version, spec):
            problems.append(f"« {dep} » : le marketplace propose {version}, mais {spec} est exigé.")
            return
        seen.add(dep)
        for sub_dep, sub_spec in sub.items():
            need(sub_dep, sub_spec, (*chain, dep))
        order.append(dep)

    for dep, spec in wanted.items():
        need(dep, spec, ())
    return order, problems
