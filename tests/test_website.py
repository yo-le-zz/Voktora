"""Contrôles statiques du site (WebSite/), sans navigateur."""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "WebSite"
PAGES = sorted(SITE.glob("*.html"))


class _Scan(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.refs: list[str] = []
        self.ids: set[str] = set()
        self.title = ""
        self.lang = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html":
            self.lang = a.get("lang") or ""
        if tag == "title":
            self._in_title = True
        if a.get("id"):
            self.ids.add(a["id"])
        for key in ("href", "src"):
            if a.get(key):
                self.refs.append(a[key])

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def _scan(path: Path) -> _Scan:
    s = _Scan()
    s.feed(path.read_text(encoding="utf-8"))
    return s


def test_pages_exist():
    names = {p.name for p in PAGES}
    assert {"index.html", "download.html", "features.html", "plugins.html", "docs.html", "changelog.html", "404.html"} <= names


def test_title_and_lang():
    for p in PAGES:
        s = _scan(p)
        assert s.title.strip(), p.name
        assert s.lang == "fr", p.name


def test_relative_links_and_resources_exist():
    for p in PAGES:
        s = _scan(p)
        for ref in s.refs:
            u = urlparse(ref)
            if u.scheme or ref.startswith(("//", "mailto:", "#")):
                continue
            target = SITE / unquote(u.path.lstrip("/")) if u.path else p
            if target.is_dir() or not u.path.strip("/"):
                target = SITE / "index.html"
            assert target.is_file(), f"{p.name}: {ref}"
            if u.fragment and target.suffix == ".html":
                assert u.fragment in _scan(target).ids, f"{p.name}: ancre {ref}"


def test_json_valid_and_shaped():
    plugins = json.loads((SITE / "data" / "plugins.json").read_text(encoding="utf-8"))
    assert plugins["plugins"] and plugins["count"] == len(plugins["plugins"])
    for item in plugins["plugins"]:
        assert {"id", "name", "lang", "description", "tags"} <= set(item)
    log = json.loads((SITE / "data" / "changelog.json").read_text(encoding="utf-8"))
    assert log["versions"] and all(v["version"] and v["sections"] for v in log["versions"])


def test_data_is_fresh():
    import subprocess
    import sys

    done = subprocess.run([sys.executable, str(ROOT / "tools" / "gen_site_data.py"), "--check"], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr


def test_displayed_version_matches_version_txt():
    version = (ROOT / "voktora" / "version.txt").read_text(encoding="utf-8").strip()
    for name in ("index.html", "download.html"):
        assert version in (SITE / name).read_text(encoding="utf-8"), name
    for p in PAGES:
        text = p.read_text(encoding="utf-8")
        shown = set(re.findall(r"\b(?:voktora|Voktora)[_ -](\d+\.\d+\.\d+)", text)) | set(re.findall(r"badge[^>]*>v(\d+\.\d+\.\d+)", text))
        assert shown <= {version}, (p.name, shown)


def test_static_extras():
    assert (SITE / "robots.txt").is_file() and (SITE / "sitemap.xml").is_file() and (SITE / "favicon.ico").is_file()
