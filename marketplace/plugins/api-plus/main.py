"""API Plus — aides publiées pour les autres plugins : `plus = api.plugin("api-plus")`.

    plus.fmt_bytes(1536)          → "1,5 Ko"          plus.fmt_duration(3725) → "1 h 02 min"
    plus.slug("Été 2026 !")       → "ete-2026"          plus.debounce(fn, 0.4)  → fonction anti-rebond
    plus.Store(api, "notes.json") → dict persistant      plus.bus                → bus d'événements entre plugins
    plus.Cache(ttl=30)            → cache à durée de vie
"""

from .helpers import Bus, Cache, Store, debounce, fmt_bytes, fmt_duration, slug  # noqa: F401


def on_load(api):
    api.provide(type("Plus", (), {
        "fmt_bytes": staticmethod(fmt_bytes), "fmt_duration": staticmethod(fmt_duration), "slug": staticmethod(slug),
        "debounce": staticmethod(debounce), "Store": Store, "Cache": Cache, "bus": Bus(),
        "version": "1.0.0",
    })())
    api.log("API Plus prête")

