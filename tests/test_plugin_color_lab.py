"""Color Lab : analyse de couleurs, conversions, contraste WCAG, correction, palettes, dialogue."""

import pytest
from plugin_stub import StubApi, load_plugin, submodule


@pytest.fixture(scope="module")
def plg():
    return load_plugin("color-lab"), submodule("color-lab", "core")


def test_parse_formats(plg):
    _m, c = plg
    assert c.parse("#fff") == (255, 255, 255) and c.parse("3E63DD") == (62, 99, 221)
    assert c.parse("rgb(10, 20, 300)") == (10, 20, 255) and c.parse("rgba(1 2 3 / 50%)") == (1, 2, 3)
    assert c.parse("hsl(0, 100%, 50%)") == (255, 0, 0) and c.parse("hsl(120deg 100% 25%)") == (0, 128, 0)
    for bad in ("", "#12", "rouge", "rgb(1,2)", "#gggggg"):
        with pytest.raises(ValueError):
            c.parse(bad)


def test_roundtrip_and_formats(plg):
    _m, c = plg
    for rgb in [(0, 0, 0), (255, 255, 255), (62, 99, 221), (200, 30, 90)]:
        h, s, light = c.to_hsl(rgb)
        back = c.parse(f"hsl({h}, {s}%, {light}%)")
        assert all(abs(a - b) <= 3 for a, b in zip(rgb, back, strict=True))
        assert c.parse(c.to_hex(rgb)) == rgb
    assert c.formats((255, 0, 0)) == {"HEX": "#FF0000", "RGB": "rgb(255, 0, 0)", "HSL": "hsl(0, 100%, 50%)"}


def test_wcag_reference_values(plg):
    _m, c = plg
    assert c.contrast((0, 0, 0), (255, 255, 255)) == pytest.approx(21.0)          # valeur de référence WCAG
    assert c.contrast((255, 255, 255), (255, 255, 255)) == pytest.approx(1.0)
    assert c.contrast((119, 119, 119), (255, 255, 255)) == pytest.approx(4.48, abs=0.02)     # #777 sur blanc : juste sous AA
    v = c.verdict(4.5)
    assert v["AA"] and not v["AAA"] and v["AA grand texte"] and v["AAA grand texte"]
    assert c.best_text((0, 0, 0)) == (255, 255, 255) and c.best_text((250, 250, 250)) == (0, 0, 0)


def test_fix_contrast(plg):
    _m, c = plg
    fg, bg = (150, 150, 255), (255, 255, 255)
    assert c.contrast(fg, bg) < 4.5
    fixed = c.fix_contrast(fg, bg)
    assert c.contrast(fixed, bg) >= 4.5 and fixed[2] > fixed[0]                    # teinte bleutée conservée
    assert c.fix_contrast((0, 0, 0), bg) == (0, 0, 0)                               # déjà conforme : inchangé
    dark_fix = c.fix_contrast((40, 40, 60), (20, 20, 30))
    assert c.contrast(dark_fix, (20, 20, 30)) >= 4.5                                 # fond sombre : on éclaircit
    assert c.contrast(c.fix_contrast((128, 128, 128), (128, 128, 128), 21), (128, 128, 128)) > 4


def test_palettes(plg):
    _m, c = plg
    p = c.palettes((255, 0, 0))
    assert p["Complémentaire"][1] == (0, 255, 255) and len(p["Triade"]) == 3 and len(p["Tétrade"]) == 4
    assert p["Triade"][1] == (0, 255, 0) and len(p["Nuances"]) == 7
    assert c.luminance(p["Nuances"][0]) > c.luminance(p["Nuances"][-1])


def test_dialog(plg, tmp_path):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    mod, core = plg
    api = StubApi(tmp_path)
    mod.on_load(api)
    assert api.menu[0][1] == "Color Lab…"
    dlg = mod.ColorDialog(api)
    assert dlg.error.text() == "" and "Contraste" in dlg.report.text()
    dlg.base.setText("#9999ff")
    assert dlg.fix_btn.isEnabled()
    dlg.fix()
    assert core.contrast(*dlg.colors()) >= 4.5 and not dlg.fix_btn.isEnabled()
    dlg.base.setText("n'importe quoi")
    assert "illisible" in dlg.error.text()
    dlg.base.setText("rgb(255, 0, 0)")
    dlg.copy("#FF0000")
    assert api.clipboard == "#FF0000" and api.notices
