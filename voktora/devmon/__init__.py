"""
Voktora — devmon (1.1.3) : moniteur développeur GLOBAL dans un processus séparé.

L'application écrit ses événements (plantages, erreurs, journaux, clics, menus, blocages de l'interface…) dans un fichier
JSON Lines ; une SECONDE fenêtre, lancée comme processus DÉTACHÉ (elle ne bloque pas la fenêtre principale et survit à un
plantage de Voktora), relit ce fichier en direct. Quatre modes règlent la quantité d'informations :

  crash    plantages seulement (exceptions non gérées, plantage natif, arrêt anormal)
  normal   + erreurs, avertissements, démarrage/arrêt, fenêtres et boîtes de dialogue ouvertes, erreurs des plugins
  verbose  + clics, menus, raccourcis, onglets, hooks de plugins, écritures de configuration, blocages de l'interface,
           commandes lancées (git…), connexions réseau, fichiers supprimés/déplacés, sorties console, journaux des panneaux et de la synchro
  trace    + messages Qt, journaux DEBUG, changements de focus, durée des hooks, écritures de fichiers, DNS

Confidentialité : jamais le texte saisi au clavier (seulement les raccourcis), jamais le contenu des champs ni des listes,
secrets masqués (jetons, mots de passe), fenêtres de coffre/mot de passe ignorées. Tout reste sur la machine.
"""

from .core import LABELS, LEVELS, RANK  # noqa: F401


def open_monitor(level: str = "normal", app=None, open_window: bool = True):
    """Active l'observation dans ce processus (si besoin), règle le mode, ouvre la fenêtre détachée. Renvoie l'Emitter."""
    from . import emitter, launcher
    em = emitter.current()
    if em is None:
        em = emitter.start(level, app)
    else:
        em.set_level(level)
    if open_window:
        launcher.launch_viewer(em.session, em.secret)
    return em


def note(msg: str, cat: str = "log", sev: str = "info", need: str = "normal", src: str = "app", data: dict | None = None) -> None:
    """Écrit une ligne dans le journal du moniteur si celui-ci est actif (sinon ne fait rien, sans coût). À utiliser partout où
    l'application affiche quelque chose à l'utilisateur : le journal global reflète alors tout ce qu'il voit."""
    try:
        from . import emitter
        em = emitter.current()
        if em is not None:
            import re as _re
            em.emit(cat, _re.sub(r"<[^>]+>", "", str(msg))[:2000], sev=sev, need=need, src=src, data=data)
    except Exception:  # noqa: BLE001 — l'observateur ne doit jamais casser l'application
        pass
