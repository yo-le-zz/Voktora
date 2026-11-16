"""Modèles de workflows d'exemple, ouvrables en un clic. Chaque modèle est valide (aucune erreur) et utilise des blocs sûrs."""

from __future__ import annotations

import copy

from . import blocks, schema, validation


def _node(id_, type_, x, y, label="", **params):
    n = {"id": id_, "type": type_, "label": label or blocks.REGISTRY[type_].title, "params": params, "options": {}, "x": x, "y": y}
    return schema.upgrade_node(n)


def _wf(name, description, nodes, edges, triggers=None):
    return {"schema": 1, "name": name, "description": description, "enabled": True, "triggers": triggers or [{"kind": "manual"}],
            "nodes": [validation.new_workflow()["nodes"][0], *nodes], "edges": [{"src": s, "port": p, "dst": d} for s, p, d in edges]}


def _tests_puis_notification():
    return _wf("Tests puis notification", "Lance les tests du projet et prévient du résultat.", [
        _node("tests", "project_command", 220, 0, "Lancer les tests", command="python -m pytest -q", timeout=600),
        _node("ok", "notify", 460, -60, "Tout est vert", message="Tests réussis"),
        _node("ko", "notify", 460, 70, "Tests en échec", message="Tests en échec : code {{out.tests.code}}")],
        [("start", "out", "tests"), ("tests", "out", "ok"), ("tests", "error", "ko")])


def _appel_api():
    return _wf("Appeler une API et lire le JSON", "Requête GET, lecture de la réponse, puis journal.", [
        _node("api", "http_request", 220, 0, "Requête GET", method="GET", url="https://api.github.com/repos/yo-le-zz/Voktora", headers='{"Accept": "application/vnd.github+json"}', timeout=30),
        _node("lire", "parse_json", 440, 0, "Lire la réponse", text="{{out.api.body}}"),
        _node("journal", "log", 660, 0, "Afficher", message="Statut {{out.api.status}} — étoiles : {{get(out.lire.value, 'stargazers_count', 0)}}", level="info")],
        [("start", "out", "api"), ("api", "out", "lire"), ("lire", "out", "journal")])


def _chercher_todo():
    return _wf("Chercher les TODO", "Cherche TODO/FIXME dans le code et prévient s'il y en a.", [
        _node("chercher", "project_search", 220, 0, "Chercher", pattern="TODO|FIXME", glob="**/*.py", limit=100),
        _node("test", "if", 440, 0, "Y en a-t-il ?", condition="out.chercher.count > 0"),
        _node("oui", "notify", 660, -60, "Prévenir", message="{{out.chercher.count}} TODO/FIXME trouvés"),
        _node("non", "log", 660, 70, "Rien à signaler", message="Aucun TODO.", level="info")],
        [("start", "out", "chercher"), ("chercher", "out", "test"), ("test", "true", "oui"), ("test", "false", "non")])


def _boucle_fichiers():
    return _wf("Parcourir des fichiers", "Liste des fichiers puis une ligne de journal par fichier (boucle).", [
        _node("liste", "list_files", 220, 0, "Lister", pattern="*.md", limit=50),
        _node("boucle", "loop_for", 440, 0, "Pour chaque fichier", items="out.liste.files", max_items=50),
        _node("ligne", "log", 660, -60, "Écrire le nom", message="Fichier n°{{index}} : {{item}}", level="info"),
        _node("fin", "notify", 660, 70, "Terminé", message="{{out.liste.count}} fichiers parcourus")],
        [("start", "out", "liste"), ("liste", "out", "boucle"), ("boucle", "body", "ligne"), ("boucle", "done", "fin")])


def _build_parallele():
    return _wf("Build en parallèle", "Deux commandes lancées en même temps, puis une notification.", [
        _node("par", "parallel", 200, 0, "En parallèle", max_workers=2),
        _node("lint", "project_command", 420, -70, "Lint", command="ruff check .", timeout=300),
        _node("tests", "project_command", 420, 70, "Tests", command="python -m pytest -q", timeout=600),
        _node("join", "join", 640, 0),
        _node("fin", "notify", 840, 0, "Terminé", message="Lint et tests terminés")],
        [("start", "out", "par"), ("par", "out", "lint"), ("par", "out", "tests"), ("lint", "out", "join"), ("tests", "out", "join"), ("join", "out", "fin")])


def _git_pull_tests():
    return _wf("Mettre à jour puis tester", "git pull (fast-forward) puis les tests ; arrêt si l'un échoue.", [
        _node("pull", "git_pull", 220, 0, "Mettre à jour"),
        _node("tests", "run_command", 440, 0, "Tests", command="python -m pytest -q", cwd="", timeout=600, fail_on_error=True),
        _node("fin", "set_var", 660, 0, "Retenir le résultat", name="dernier_code", value="out.tests.code")],
        [("start", "out", "pull"), ("pull", "out", "tests"), ("tests", "out", "fin")])


TEMPLATES = {
    "tests": ("Tests puis notification", _tests_puis_notification),
    "api": ("Appeler une API et lire le JSON", _appel_api),
    "todo": ("Chercher les TODO", _chercher_todo),
    "fichiers": ("Parcourir des fichiers", _boucle_fichiers),
    "parallele": ("Build en parallèle", _build_parallele),
    "git": ("Mettre à jour puis tester", _git_pull_tests),
}


def template_list() -> list[tuple[str, str]]:
    return [(k, v[0]) for k, v in TEMPLATES.items()]


def build(key: str) -> dict:
    """Nouveau workflow indépendant (copie profonde) à partir d'un modèle."""
    return copy.deepcopy(TEMPLATES[key][1]())
