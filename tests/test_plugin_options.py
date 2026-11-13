"""API 5 : options de plugin (déclaration, contrôle des valeurs, panneau automatique)."""

import pytest
from plugins import runtime
from plugins.options import OptionError, PluginOptions


class Store:
    def __init__(self):
        self.d = {}

    def get(self, k, default=None):
        return self.d.get(k, default)

    def set(self, k, v):
        self.d[k] = v


def make():
    errors = []
    o = PluginOptions(Store(), errors.append)
    o.group("Apparence")
    o.add_int("taille", "Taille", default=12, min=8, max=32)
    o.add_choice("style", "Style", ["clair", "sombre"], default="sombre")
    o.add_bool("gras", "Gras", True)
    o.add_color("accent", "Accent", "#112233")
    o.add_text("nom", "Nom", "x", visible_if=("gras", True))
    return o, errors


def test_defaults_clamp_and_validation():
    o, _ = make()
    assert o.values() == {"taille": 12, "style": "sombre", "gras": True, "accent": "#112233", "nom": "x"}
    assert o.set("taille", 999) == 32 and o.get("taille") == 32
    with pytest.raises(OptionError):
        o.set("style", "rose")
    with pytest.raises(OptionError):
        o.set("accent", "rouge")
    with pytest.raises(OptionError):
        o.set("inconnue", 1)
    with pytest.raises(OptionError):
        o.add_int("taille", "doublon")


def test_hand_edited_invalid_value_falls_back():
    o, _ = make()
    o._store.set("_options", {"taille": "abc", "style": "rose"})
    assert o.get("taille") == 12 and o.get("style") == "sombre"


def test_on_change_and_failing_listener_contained():
    o, errors = make()
    seen = []
    o.on_change(lambda k, v: seen.append((k, v)))
    o.on_change(lambda k, v: 1 / 0)
    o.set("taille", 20)
    o.set("taille", 20)                          # inchangé : pas de notification
    assert seen == [("taille", 20)] and len(errors) == 1
    o.reset("taille")
    assert o.get("taille") == 12 and seen[-1] == ("taille", 12)


def test_visibility_rule():
    o, _ = make()
    nom = next(x for x in o.schema() if x.key == "nom")
    assert o.is_visible(nom)
    o.set("gras", False)
    assert not o.is_visible(nom)


def test_panel_builds_and_edits(isolated_data_dir):
    from PySide6.QtWidgets import QApplication, QSpinBox
    from ui_dialogs.plugin_options_panel import PluginOptionsPanel
    _app = QApplication.instance() or QApplication([])
    assert _app is not None
    o, _ = make()
    o.add_button("Action", lambda: None)
    panel = PluginOptionsPanel(o)
    spin = panel.findChild(QSpinBox)
    spin.setValue(30)
    assert o.get("taille") == 30
    panel._reset()
    assert o.get("taille") == 12


def test_plugin_gets_options_through_api(isolated_data_dir, tmp_path):
    info = runtime.PluginInfo(name="t", version="1", author="a", path=tmp_path, id="t")
    api = runtime.PluginAPI(info)
    api.options.add_bool("x", "X", True)
    assert info.options is api.options and api.options.get("x") is True
