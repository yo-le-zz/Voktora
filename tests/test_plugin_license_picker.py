"""License Picker : textes, substitution, en-têtes SPDX, détection, dialogue."""

import pytest
from plugin_stub import StubApi, load_plugin, submodule


@pytest.fixture(scope="module")
def plg():
    return load_plugin("license-picker"), submodule("license-picker", "core")


def test_catalog_and_render(plg):
    _m, core = plg
    lic = core.licenses()
    assert {"MIT", "BSD-2-Clause", "BSD-3-Clause", "ISC", "Unlicense", "Apache-2.0", "GPL-3.0-or-later", "MPL-2.0"} <= set(lic)
    mit = core.render("MIT", "Ana Martin", 2026)
    assert mit.startswith("MIT License\n\nCopyright (c) 2026 Ana Martin") and "{" not in mit
    assert "Neither the name" in core.render("BSD-3-Clause", "X", 2020) and "Neither the name" not in core.render("BSD-2-Clause", "X", 2020)
    assert "Les auteurs" in core.render("ISC", "  ", 2020)
    with pytest.raises(ValueError):
        core.render("GPL-3.0-or-later", "X")                     # texte long : pas inventé, lien officiel à la place
    assert not core.has_text("Apache-2.0") and all(lic[k]["url"].startswith("https://") for k in lic if "text" not in lic[k])


def test_every_text_license_is_detected_back(plg):
    _m, core = plg
    for key in ("MIT", "BSD-2-Clause", "BSD-3-Clause", "ISC", "Unlicense"):
        assert core.detect(core.render(key, "Ana", 2026)) == key
    assert core.detect("") is None and core.detect("Licence maison") is None
    assert core.detect("GNU GENERAL PUBLIC LICENSE\nVersion 3") == "GPL-3.0-or-later"


def test_spdx_headers(plg):
    _m, core = plg
    assert core.spdx_header("MIT", "Python / Shell / YAML / TOML", "Ana", 2026) == "# Copyright (c) 2026 Ana\n# SPDX-License-Identifier: MIT\n"
    assert core.spdx_header("GPL-3.0-or-later", "CSS") == "/* SPDX-License-Identifier: GPL-3.0-or-later */\n"
    assert core.spdx_header("MIT", "HTML / XML / Markdown", "Ana", 2026).startswith("<!-- Copyright")


def test_dialog_writes_and_copies(plg, tmp_path):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    mod, core = plg
    proj = tmp_path / "demo"
    proj.mkdir()
    api = StubApi(tmp_path / "d", proj)
    mod.on_load(api)
    api.options.set("holder", "Ana")
    dlg = mod.LicenseDialog(api, proj, api.options.get("holder"))
    assert "Aucun fichier LICENSE" in dlg._status.text() and dlg.holder.text() == "Ana" and dlg.write_btn.isEnabled()
    dlg.write()
    assert "Copyright (c)" in (proj / "LICENSE").read_text() and "Ana" in (proj / "LICENSE").read_text()
    assert "Licence actuelle : MIT" in dlg._status.text()
    dlg.copy_header()
    assert "SPDX-License-Identifier: MIT" in api.clipboard
    dlg.combo.setCurrentIndex(list(core.licenses()).index("Apache-2.0"))
    assert not dlg.write_btn.isEnabled() and not dlg.link_btn.isHidden() and "apache.org" in dlg.preview.toPlainText()
    dlg.open_official()
    assert api.opened.startswith("https://www.apache.org")
    assert mod.LicenseDialog(api, proj, "").combo.currentData() == "MIT"
