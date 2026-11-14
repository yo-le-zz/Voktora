"""
Voktora — devmon (1.1.3) : moniteur développeur GLOBAL dans un processus séparé.

L'application écrit ses événements (plantages, erreurs, journaux, clics, menus, blocages de l'interface…) dans un fichier
JSON Lines ; une SECONDE fenêtre, lancée comme processus DÉTACHÉ (elle ne bloque pas la fenêtre principale et survit à un
plantage de Voktora), relit ce fichier en direct. Quatre modes règlent la quantité d'informations :

  crash    plantages seulement (exceptions non gérées, plantage natif, arrêt anormal)
  normal   + erreurs, avertissements, démarrage/arrêt, fenêtres et boîtes de dialogue ouvertes, erreurs des plugins
  verbose  + clics, menus, raccourcis, onglets, hooks de plugins, écritures de configuration, blocages de l'interface
  trace    + messages Qt, journaux DEBUG, changements de focus, durée des hooks

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
        launcher.launch_viewer(em.session)
    return em
