"""Beaucoup de projets (105) : la synchronisation doit rester rapide, et la 2e passe quasi instantanée."""

import time

from sync.service import DONE
from test_sync import pcs, write  # noqa: F401


def test_105_projects(pcs):  # noqa: F811
    main, laptop = pcs
    for i in range(105):
        folder = main.cfg.add_project(f"p{i:03d}")
        for j in range(12):
            write(folder, f"src/f{j}.txt", f"{i}-{j}\n")
    t0 = time.monotonic()
    laptop.svc.sync_peer(main.id, "primary")
    first = time.monotonic() - t0
    assert laptop.svc.status[main.id]["state"] == DONE
    assert len(list((laptop.cfg.projects_root()).glob("p*/src/f*.txt"))) == 105 * 12
    t0 = time.monotonic()
    laptop.svc.sync_peer(main.id)
    second = time.monotonic() - t0
    assert laptop.svc.status[main.id]["summary"] in ("Tout est à jour.", "déjà à jour")
    assert second < 2                      # 2e passe : vérification rapide par empreintes, même en mode économe
    t0 = time.monotonic()
    laptop.svc.sync_peer(main.id, full=True)                      # la vérification complète reste correcte et raisonnable
    assert laptop.svc.status[main.id]["summary"] == "Tout est à jour." and time.monotonic() - t0 < 6
    print(f"\n105 projets : 1re synchro {first:.1f}s, 2e passe rapide {second:.1f}s")
    cache = laptop.svc.store._cache
    assert cache is not None and len(cache) <= 105 * 12 + 50          # pas de gonflement du cache
