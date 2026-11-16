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


def _test_basique():
    return _wf("Test (données entre blocs)", "Workflow de test sans danger : variable, liste de fichiers, condition, lecture d'un fichier et transmission de son contenu au bloc suivant.", [
        _node("nom", "set_var", 220, 0, "Définir le nom", name="nom", value="'Voktora'"),
        _node("salut", "log", 440, 0, "Dire bonjour", message="Bonjour {{vars.nom}} !", level="info"),
        _node("liste", "list_files", 660, 0, "Lister les .md", pattern="*.md", limit=20),
        _node("any", "if", 880, 0, "Y a-t-il un .md ?", condition="out.liste.count > 0"),
        _node("lire", "read_file", 1100, -80, "Lire le premier", path="{{out.liste.files[0]}}", max_bytes=2000),
        _node("apercu", "log", 1320, -80, "Afficher le début", message="Début de {{out.liste.files[0]}} : {{out.lire.text[:80]}}", level="info"),
        _node("rien", "log", 1100, 80, "Aucun fichier", message="Aucun fichier Markdown dans le projet.", level="warning"),
        _node("fin", "notify", 1540, 0, "Terminé", message="Test terminé pour {{vars.nom}}")],
        [("start", "out", "nom"), ("nom", "out", "salut"), ("salut", "out", "liste"), ("liste", "out", "any"), ("any", "true", "lire"),
         ("lire", "out", "apercu"), ("apercu", "out", "fin"), ("any", "false", "rien"), ("rien", "out", "fin")])


def _ci_complete():
    return _wf("Pipeline CI complet", "État Git, lint + tests + recherche de TODO en parallèle, rapport écrit dans un fichier avec les résultats de tous les blocs, puis notification.", [
        _node("head", "git_head", 220, 0, "Commit courant"),
        _node("statut", "git_status", 440, 0, "État du dépôt"),
        _node("propre", "if", 660, 0, "Dépôt propre ?", condition="out.statut.clean"),
        _node("avert", "log", 880, -190, "Prévenir", message="⚠ {{out.statut.changes}} modification(s) non commitées", level="warning"),
        _node("par", "parallel", 900, 0, "Contrôles en parallèle", max_workers=3),
        _node("lint", "project_command", 1140, -140, "Lint", command="ruff check .", timeout=300),
        _node("tests", "project_command", 1140, 0, "Tests", command="python -m pytest -q", timeout=900),
        _node("todo", "project_search", 1140, 140, "TODO restants", pattern="TODO|FIXME", glob="**/*.py", limit=200),
        _node("join", "join", 1380, 0),
        _node("bilan", "set_var", 1600, 0, "Calculer le bilan", name="ok", value="out.lint.ok != False and out.tests.ok != False"),
        _node("verdict", "if", 1820, 0, "Tout est vert ?", condition="vars.ok"),
        _node("rapport", "write_file", 2040, -90, "Écrire le rapport", path="ci-rapport.txt", mode="w",
              content="Commit {{out.head.sha}}\nLint : {{out.lint.ok}}\nTests : {{out.tests.ok}} ({{out.tests.seconds}} s)\nTODO : {{out.todo.count}}"),
        _node("bravo", "notify", 2260, -90, "Succès", message="CI verte — {{out.todo.count}} TODO"),
        _node("echec", "fail", 2040, 100, "Échec CI", message="CI en échec : lint={{out.lint.ok}} tests={{out.tests.ok}}")],
        [("start", "out", "head"), ("head", "out", "statut"), ("statut", "out", "propre"), ("propre", "true", "par"), ("propre", "false", "avert"), ("avert", "out", "par"),
         ("par", "out", "lint"), ("par", "out", "tests"), ("par", "out", "todo"), ("lint", "out", "join"), ("lint", "error", "join"), ("tests", "out", "join"),
         ("tests", "error", "join"), ("todo", "out", "join"), ("join", "out", "bilan"), ("bilan", "out", "verdict"), ("verdict", "true", "rapport"),
         ("verdict", "false", "echec"), ("rapport", "out", "bravo")])


def _rapport_lignes():
    return _wf("Compter les lignes du code", "Boucle sur les fichiers Python : lit chacun, cumule le nombre de lignes dans une variable, puis écrit un rapport.", [
        _node("zero", "set_var", 220, 0, "Total = 0", name="total", value="0"),
        _node("liste", "list_files", 440, 0, "Lister les .py", pattern="**/*.py", limit=300),
        _node("boucle", "loop_for", 660, 0, "Pour chaque fichier", items="out.liste.files", max_items=300),
        _node("lire", "read_file", 900, -90, "Lire", path="{{item}}", max_bytes=500000),
        _node("somme", "set_var", 1120, -90, "Ajouter les lignes", name="total", value="vars.total + len(split(out.lire.text, '\\n'))"),
        _node("rapport", "write_file", 900, 110, "Écrire le rapport", path="lignes-code.txt", mode="w",
              content="{{out.liste.count}} fichiers Python, {{vars.total}} lignes au total"),
        _node("fin", "notify", 1120, 110, "Terminé", message="{{vars.total}} lignes dans {{out.liste.count}} fichiers")],
        [("start", "out", "zero"), ("zero", "out", "liste"), ("liste", "out", "boucle"), ("boucle", "body", "lire"), ("lire", "out", "somme"),
         ("boucle", "done", "rapport"), ("rapport", "out", "fin")])


def _surveillance_api():
    return _wf("Surveiller une API avec reprises", "Requête avec 3 essais, lecture du JSON, branches selon le statut, avertissement si l'API est en panne.", [
        _node("seuil", "set_var", 220, 0, "Seuil d'étoiles", name="seuil", value="10"),
        _node("api", "http_request", 440, 0, "Interroger l'API", method="GET", url="https://api.github.com/repos/yo-le-zz/Voktora", headers='{"Accept": "application/vnd.github+json"}', timeout=20),
        _node("json", "parse_json", 680, -70, "Lire la réponse", text="{{out.api.body}}"),
        _node("ok", "if", 900, -70, "Assez d'étoiles ?", condition="get(out.json.value, 'stargazers_count', 0) >= vars.seuil"),
        _node("bien", "log", 1120, -150, "Au-dessus du seuil", message="{{get(out.json.value, 'stargazers_count', 0)}} étoiles (≥ {{vars.seuil}})", level="info"),
        _node("bas", "log", 1120, -10, "Sous le seuil", message="Seulement {{get(out.json.value, 'stargazers_count', 0)}} étoiles", level="warning"),
        _node("panne", "notify", 680, 120, "API injoignable", message="API en panne : {{out.api.error}}"),
        _node("fin", "log", 1340, -70, "Terminé", message="Contrôle terminé (statut HTTP {{out.api.status}})", level="info")],
        [("start", "out", "seuil"), ("seuil", "out", "api"), ("api", "out", "json"), ("api", "error", "panne"), ("json", "out", "ok"), ("ok", "true", "bien"),
         ("ok", "false", "bas"), ("bien", "out", "fin"), ("bas", "out", "fin")])


TEMPLATES = {
    "tests": ("Tests puis notification", _tests_puis_notification),
    "api": ("Appeler une API et lire le JSON", _appel_api),
    "todo": ("Chercher les TODO", _chercher_todo),
    "fichiers": ("Parcourir des fichiers", _boucle_fichiers),
    "parallele": ("Build en parallèle", _build_parallele),
    "git": ("Mettre à jour puis tester", _git_pull_tests),
    "test": ("Test (données entre blocs)", _test_basique),
    "ci": ("Pipeline CI complet", _ci_complete),
    "lignes": ("Compter les lignes du code", _rapport_lignes),
    "surveillance": ("Surveiller une API avec reprises", _surveillance_api),
}


def template_list() -> list[tuple[str, str]]:
    return [(k, v[0]) for k, v in TEMPLATES.items()]


def build(key: str) -> dict:
    """Nouveau workflow indépendant (copie profonde) à partir d'un modèle."""
    return copy.deepcopy(TEMPLATES[key][1]())
