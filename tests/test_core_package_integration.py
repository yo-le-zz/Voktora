"""
Test d'intégration : vérifie que le découpage de core.py en package
(core/constants, paths, config_store, drives, crypto, github_auth,
projects, git_ops, system, diagnostics) n'a rien cassé de bout en bout —
en particulier les références croisées entre sous-modules qualifiées
automatiquement pendant le découpage (config_store.paths.get_data_dir(),
projects.config_store._load_config(), etc.).
"""

import core


class TestCorePackageIntegration:
    def test_create_list_delete_instance_round_trip(self, isolated_data_dir, tmp_path):
        drive = str(tmp_path)
        core.set_storage_config(str(tmp_path / "Instances"), str(tmp_path / "Intents"))

        path = core.create_instance(drive, "MonProjetTest")
        assert path.exists()

        names = [i["name"] for i in core.list_instances()]
        assert "MonProjetTest" in names

        core.set_instance_note(path, "une note de test")
        assert core.get_instance_note(path) == "une note de test"

        core.delete_instance(path)
        names_after = [i["name"] for i in core.list_instances()]
        assert "MonProjetTest" not in names_after

    def test_health_check_runs_across_all_submodules(self, isolated_data_dir):
        # run_health_check() (diagnostics) touche config_store, github_auth
        # et paths — un bon canari pour détecter une référence croisée cassée.
        result = core.run_health_check()
        assert hasattr(result, "issues")

    def test_repair_config_invalidates_and_rewrites_cache(self, isolated_data_dir):
        # repair_config() invalide le cache partagé au milieu de sa logique
        # (via config_store.invalidate_cache(), pour forcer une lecture
        # fraîche depuis le disque), puis le re-remplit naturellement avec
        # la config réparée en appelant _save_config() à la fin.
        core._load_config()
        first_cache_id = id(core.config_store._config_cache)

        ok, msg = core.repair_config()
        assert ok is True

        # Le cache a bien été régénéré (nouvel objet), pas simplement
        # laissé tel quel — preuve que invalidate_cache() a eu effet.
        assert id(core.config_store._config_cache) != first_cache_id
        assert core.config_store._config_cache is not None

    def test_facade_reflects_submodule_state_dynamically(self, isolated_data_dir):
        # Le point critique de l'architecture en façade : patcher le
        # sous-module propriétaire doit être visible via core.X.
        assert core.get_data_dir() == core.paths.get_data_dir()

    def test_writing_constants_via_owning_submodule_is_visible_everywhere(self, isolated_data_dir):
        # Régression : écrire sur la façade (core.APP_VERSION = v) ne
        # mettrait à jour QUE le dict du package __init__, pas
        # core.constants.APP_VERSION — désynchronisant tous les appels
        # internes qui lisent constants.APP_VERSION en qualifié (User-Agent
        # des requêtes GitHub, comparaison de version pour les mises à
        # jour...). Écrire via core.constants.APP_VERSION est la bonne
        # méthode : la façade doit alors refléter le changement aussi.
        original = core.constants.APP_VERSION
        try:
            core.constants.APP_VERSION = "9.9.9-test"
            assert core.APP_VERSION == "9.9.9-test"
        finally:
            core.constants.APP_VERSION = original

class TestAppVersion:
    def test_app_version_is_1_0_2(self):
        assert core.APP_VERSION == "1.0.2"
