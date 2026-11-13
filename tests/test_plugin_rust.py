"""Plugins Rust 1.1.1 : compilation cargo, chargement, appels API, empreinte (ignoré sans cargo/SDK/réseau)."""

import json
import shutil

import plugins
import pytest
from plugins import rust_host

pytestmark = pytest.mark.skipif(rust_host.cargo_path() is None or rust_host.sdk_dir() is None,
                                reason="cargo ou SDK Rust absent")

CARGO = """[package]
name = "rust-hello"
version = "0.1.0"
edition = "2021"

[lib]
crate-type = ["cdylib"]

[dependencies]
voktora-plugin = { path = "../voktora-sdk" }
"""
LIB = """use voktora_plugin::{plugin, Api};
plugin!(on_load, on_unload);
fn on_load(api: &Api) {
    api.log("salut rust");
    let n = api.options();
    n.add_int("n", "N", 5, 1, 10);
    api.on("on_open", |a, _ctx| { a.log("open rust"); });
}
fn on_unload(api: &Api) { api.log("bye rust"); }
"""


def test_rust_plugin_builds_and_runs(isolated_data_dir):
    d = plugins.plugins_dir()
    folder = d / "rust-hello"
    (folder / "src").mkdir(parents=True)
    (folder / "plugin.json").write_text(json.dumps({"id": "rust-hello", "name": "r", "version": "1.0.0", "author": "t", "api": 5,
                                                    "lang": "rust", "entry": "Cargo.toml", "permissions": "auto"}))
    (folder / "Cargo.toml").write_text(CARGO)
    (folder / "src" / "lib.rs").write_text(LIB)
    info_ready = None
    try:
        plugins.load_all()
        info = plugins.find("rust-hello")
        assert info is not None
        import time
        deadline = time.time() + 900
        while time.time() < deadline and (info.pending_libs or not info.loaded) and not (info.error and not info.pending_libs):
            time.sleep(0.5)
        assert info.loaded, info.error
        assert any("salut rust" in line for line in info.logs)
        assert rust_host.is_built(info)
        plugins.fire_hook("on_open", __import__("pathlib").Path("/tmp/proj"))
        assert any("open rust" in line for line in info.logs)
        info_ready = info
    finally:
        if info_ready:
            plugins.set_enabled("rust-hello", False)
        shutil.rmtree(folder, ignore_errors=True)
        plugins.load_all()
