"""
Voktora — plugins.api_ext (API de plugins v3 + v4, Voktora 1.1.0)
Méthodes supplémentaires de `PluginAPI` : réglages, actions rapides, snapshots, espace disque, forges,
synchronisation, plugins et SÉCURITÉ. Chaque méthode exige une permission déclarée dans `plugin.json`.
Règle d'or : ce qui lit est libre une fois la permission accordée ; ce qui MODIFIE la sécurité (coffre, plugins,
synchronisation) passe toujours par une confirmation de l'utilisateur, montrée avec le nom du plugin.
Les jetons, mots de passe et secrets ne sont JAMAIS exposés, même avec toutes les permissions.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import core

SENSITIVE_WORDS = ("token", "secret", "password", "passwd", "key", "credential", "private", "pem", "auth")
PROTECTED_SETTINGS = {"plugin_market_url", "plugin_trusted_urls", "github_client_id", "auth_method"}


def is_sensitive(key: str) -> bool:
    low = key.lower()
    return key in PROTECTED_SETTINGS or any(w in low for w in SENSITIVE_WORDS)


class ExtendedAPI:
    """Mixin : s'appuie sur `_require`, `_info`, `_confirm_security` de PluginAPI."""

    # -- réglages ------------------------------------------------------------------
    def config_get(self, key: str, default: Any = None) -> Any:
        """Réglage de l'application (permission « config.read »). Les clés sensibles sont masquées."""
        self._require("config.read")
        if is_sensitive(key):
            raise self._error(f"Le réglage « {key} » est protégé : il n'est pas accessible aux plugins.")
        return core._load_config().get("app_config", {}).get(key, default)

    def config_all(self) -> dict[str, Any]:
        self._require("config.read")
        return {k: v for k, v in core._load_config().get("app_config", {}).items() if not is_sensitive(k)}

    def config_set(self, key: str, value: Any) -> None:
        """Modifie un réglage de l'application (permission « config.write », confirmation à chaque changement)."""
        self._require("config.write")
        if is_sensitive(key):
            raise self._error(f"Le réglage « {key} » est protégé : un plugin ne peut pas le modifier.")
        if not isinstance(value, str | int | float | bool | list | dict | type(None)):
            raise self._error("Valeur de réglage non sérialisable.")
        if not self._confirm_security("Modifier un réglage", f"Définir « {key} » = {value!r} ?"):
            raise self._error("Modification refusée par l'utilisateur.")
        cfg = core._load_config()
        cfg.setdefault("app_config", {})[key] = value
        core._save_config(cfg)

    # -- actions rapides -----------------------------------------------------------
    def quick_actions(self) -> list[dict]:
        self._require("quick_actions")
        import quick_actions
        return [a.to_dict() for a in quick_actions.load()]

    def quick_action_add(self, name: str, cmd: str, icon: str = "", terminal: bool = False) -> None:
        self._require("quick_actions")
        import quick_actions
        actions = quick_actions.load()
        new = quick_actions.QuickAction(name.strip(), cmd.strip(), icon or quick_actions.DEFAULT_ICON, bool(terminal))
        problem = quick_actions.validate(new, actions)
        if problem:
            raise self._error(problem)
        if not self._confirm_security("Nouvelle action rapide", f"Ajouter « {new.name} » qui lancera :\n{new.cmd}"):
            raise self._error("Ajout refusé par l'utilisateur.")
        quick_actions.save([*actions, new])

    def quick_action_remove(self, name: str) -> bool:
        self._require("quick_actions")
        import quick_actions
        actions = quick_actions.load()
        kept = [a for a in actions if a.name != name]
        if len(kept) != len(actions):
            quick_actions.save(kept)
        return len(kept) != len(actions)

    # -- snapshots -----------------------------------------------------------------
    def snapshots(self, project: str | Path) -> list[dict]:
        self._require("snapshots")
        import snapshots
        return [{"path": str(s.path), "label": getattr(s, "label", ""), "version": getattr(s, "version", 0),
                 "created": getattr(s, "created", ""), "size": getattr(s, "size", 0)}
                for s in snapshots.list_snaps(Path(project))]

    def snapshot_create(self, project: str | Path, label: str = "", note: str = "") -> str:
        """Crée un snapshot complet ; retourne son chemin. Peut être long : à appeler depuis `run_async`."""
        self._require("snapshots")
        import snapshots
        return str(snapshots.create(Path(project), label=label[:80], note=note[:400]))

    # -- espace disque -------------------------------------------------------------
    def disk_usage(self, project: str | Path) -> dict:
        """Taille d'un projet par catégorie (cache, compilation, dépendances…). Lecture seule."""
        self._require("diskusage")
        import diskusage
        usage = diskusage.scan_project(Path(project))
        return {"total": usage.total, "human": diskusage.human(usage.total),
                "items": [{"path": str(getattr(i, "path", "")), "category": getattr(i, "category", ""),
                           "size": getattr(i, "size", 0)} for i in getattr(usage, "items", [])]}

    # -- forges ------------------------------------------------------------------
    def forge_info(self, project: str | Path) -> dict:
        """Forge, dépôt et statut de fork d'un projet (analyse locale des remotes, sans réseau)."""
        self._require("forges")
        import forges
        info = forges.project_info(Path(project))
        return {"forge": info.forge_label, "repo": info.origin.full_name if info.origin else "",
                "is_fork": info.is_fork, "parent": info.parent, "remotes": info.remotes}

    def forge_accounts(self) -> list[dict]:
        """Comptes de forge connectés — sans jeton."""
        self._require("forges")
        import forges
        return forges.list_accounts()

    # -- synchronisation -----------------------------------------------------------
    def sync_status(self) -> dict:
        """État de la synchronisation entre PC (pourcentages, pairs, dernière synchro)."""
        self._require("sync")
        from sync import get_service
        snap = get_service().snapshot()
        snap.pop("log", None)
        return snap

    def sync_now(self) -> bool:
        self._require("sync")
        from sync import get_service
        service = get_service()
        if not service.settings["enabled"] or not service.settings["peers"]:
            return False
        service.refresh_now()
        return True

    # -- plugins ---------------------------------------------------------------------
    def plugins(self) -> list[dict]:
        """Plugins installés : id, version, origine, permissions, état, commit épinglé."""
        self._require("plugins.manage")
        from . import runtime
        return [{"id": p.id, "name": p.name, "version": p.version, "origin": p.origin, "tier": p.tier,
                 "permissions": list(p.permissions), "enabled": p.enabled, "loaded": p.loaded, "commit": p.commit,
                 "error": p.error} for p in runtime.load_all_cached()]

    def set_plugin_enabled(self, plugin_id: str, enabled: bool) -> bool:
        self._require("plugins.manage")
        if plugin_id == self._info.id:
            raise self._error("Un plugin ne peut pas modifier son propre état.")
        verb = "activer" if enabled else "désactiver"
        if not self._confirm_security("Gérer les plugins", f"Le plugin « {self._info.name} » veut {verb} « {plugin_id} »."):
            return False
        from . import runtime
        return runtime.set_enabled(plugin_id, enabled) is not None

    # -- sécurité ----------------------------------------------------------------------
    def security_report(self) -> dict:
        """Vue d'ensemble de la sécurité (lecture seule) : coffre, plugins, révocations, synchronisation, TLS."""
        self._require("security")
        import core.crypto as crypto

        from . import runtime
        revoked = sorted(p.id for p in runtime.load_all_cached() if runtime.revoked_entry(p.id, p.commit))
        sync = {}
        try:
            from sync import get_service
            s = get_service().settings
            sync = {"enabled": bool(s["enabled"]), "peers": len(s["peers"]), "primary": s.is_primary,
                    "port": s["port"], "network": "LAN privé / Tailscale uniquement"}
        except Exception:  # noqa: BLE001
            sync = {}
        plugins = runtime.load_all_cached()
        return {
            "vault": {"initialized": crypto.vault_is_initialized(), "unlocked": crypto.vault_is_unlocked()},
            "plugins": {"total": len(plugins),
                        "community": sum(1 for p in plugins if p.tier == "community"),
                        "local": sum(1 for p in plugins if p.origin == "local"),
                        "with_shell": [p.id for p in plugins if "shell" in p.permissions],
                        "with_network": [p.id for p in plugins if "network" in p.permissions],
                        "revoked": revoked},
            "sync": sync,
            "tls": {"verification": "enabled"},
        }

    def audit_plugin_source(self, source: str) -> list[str]:
        """Passe le code Python donné dans l'audit statique des plugins ; retourne les problèmes trouvés."""
        self._require("security")
        import tempfile

        from . import audit
        with tempfile.TemporaryDirectory(prefix="voktora-audit-") as tmp:
            path = Path(tmp) / "plugin_source.py"
            path.write_text(source[:500_000], encoding="utf-8")
            errors, warnings = audit.check_source(path, list(self._info.permissions))
        return [*(f"erreur : {e}" for e in errors), *(f"avertissement : {w}" for w in warnings)]

    def lock_vault(self) -> None:
        """Verrouille le coffre tout de suite (action sûre : aucune confirmation)."""
        self._require("vault")
        import core.crypto as crypto
        crypto.vault_lock()

    def vault_secret_get(self, name: str) -> str:
        """Secret PROPRE à ce plugin (espace « plugin:<id>:<nom> » du coffre déverrouillé)."""
        self._require("vault")
        import core.crypto as crypto
        if not crypto.vault_is_unlocked():
            raise self._error("Le coffre est verrouillé : demandez à l'utilisateur de le déverrouiller.")
        return crypto.vault_retrieve(self._vault_key(name)) or ""

    def vault_secret_set(self, name: str, value: str) -> None:
        self._require("vault")
        import core.crypto as crypto
        if not crypto.vault_is_unlocked():
            raise self._error("Le coffre est verrouillé : demandez à l'utilisateur de le déverrouiller.")
        crypto.vault_store(self._vault_key(name), str(value), domain="plugin_secret")

    def vault_secret_delete(self, name: str) -> None:
        self._require("vault")
        import core.crypto as crypto
        crypto.vault_delete(self._vault_key(name))

    def _vault_key(self, name: str) -> str:
        if not name or len(name) > 64 or not all(c.isalnum() or c in "-_." for c in name):
            raise self._error("Nom de secret invalide (lettres, chiffres, - _ . ; 64 caractères max).")
        return f"plugin:{self._info.id}:{name}"


    # -- API 4 (Voktora 1.1.0) -----------------------------------------------------------
    def fleet_states(self) -> list[dict]:
        """État Git de tous les projets (permission « fleet ») : branche, modifications, retard/avance, problèmes."""
        self._require("fleet")
        import fleet
        return [s.to_dict() for s in fleet.scan_all(workers=2)]

    def search_projects(self, query: str, content: bool = True, limit: int = 100) -> list[dict]:
        """Recherche dans les noms de projets, de fichiers et le contenu (permission « fleet »)."""
        self._require("fleet")
        import fleet
        return [h.__dict__ for h in fleet.search(str(query), content=bool(content), limit=min(int(limit), 300))]

    def project_update(self, project: str | Path, **fields: Any) -> bool:
        """Modifie description, catégorie, statut, tags, couleur ou emoji d'un projet (permission « projects.write »,
        confirmation à chaque appel)."""
        self._require("projects.write")
        allowed = {"description", "category", "status", "tags", "color", "emoji", "icon"}
        bad = set(fields) - allowed
        if bad:
            raise self._error(f"Champs non modifiables : {sorted(bad)}. Autorisés : {sorted(allowed)}.")
        if not self._confirm_security("Modifier un projet", f"Le plugin « {self._info.name} » veut modifier « "
                                      f"{Path(project).name} » : {sorted(fields)}."):
            return False
        return core.update_project(project, **fields)

    def ai_ask(self, prompt: str, max_tokens: int = 400) -> str:
        """Pose une question au fournisseur IA actif (permission « ai »). Le texte est envoyé à ce fournisseur :
        l'utilisateur confirme à chaque appel. Aucune donnée de Voktora n'est ajoutée à la question."""
        self._require("ai")
        import ai_providers
        provider = core.get_active_ai_provider()
        if not provider:
            raise self._error("Aucun fournisseur IA configuré.")
        text = str(prompt)[:4000]
        if not self._confirm_security("Question à l'IA", f"Le plugin « {self._info.name} » envoie ce texte à "
                                      f"« {provider.get('name', '?')} » :\n\n{text[:300]}"):
            raise self._error("Envoi refusé par l'utilisateur.")
        try:
            return ai_providers.generate(provider, text, max_tokens=min(int(max_tokens), 900))
        except ai_providers.AIError as exc:
            raise self._error(str(exc)) from exc
