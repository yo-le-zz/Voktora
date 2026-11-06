"""
Voktora — plugins
Système de plugins : manifeste, API v2, chargement, interface, marketplace.

Compatibilité : `import plugins` expose toujours `load_all`, `get_all`, `fire_hook`, `all_commands`,
`all_buttons`, `plugins_dir`, `PluginContext`, `PluginInfo`, `PluginAPI` comme avant la 1.0.6.
Documentation : doc/PLUGINS.md.
"""

from .manifest import API_VERSION, PERMISSIONS, Manifest, ManifestError
from .runtime import (
    EVENTS,
    PluginAPI,
    PluginButton,
    PluginCommand,
    PluginContext,
    PluginError,
    PluginInfo,
    PluginSettings,
    all_buttons,
    all_commands,
    disabled_ids,
    extra_stylesheet,
    extra_themes,
    find,
    fire_hook,
    get_all,
    get_ui_host,
    load_all,
    market_url,
    plugin_data_dir,
    plugins_dir,
    set_enabled,
    set_market_url,
    set_ui_host,
    unload,
)

__all__ = [
    "API_VERSION", "EVENTS", "PERMISSIONS", "Manifest", "ManifestError", "PluginAPI", "PluginButton",
    "PluginCommand", "PluginContext", "PluginError", "PluginInfo", "PluginSettings", "all_buttons",
    "all_commands", "disabled_ids", "extra_stylesheet", "extra_themes", "find", "fire_hook", "get_all",
    "get_ui_host", "load_all", "market_url", "plugin_data_dir", "plugins_dir", "set_enabled",
    "set_market_url", "set_ui_host", "unload",
]
