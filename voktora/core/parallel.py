"""
Voktora — core.parallel
Multi-processus (calcul) et multi-threads (entrées/sorties) pour les tâches lourdes.

  process_map  — répartit des appels CPU-bound (chiffrement, hachage…) sur plusieurs processus ;
  thread_map   — répartit des appels bloquants sur le réseau/disque/sous-processus (git clone…).

Règles :
  • les processus sont démarrés en mode « spawn » (jamais « fork ») : fork dans une application Qt
    multithread est une source classique de blocages. La fonction et ses arguments doivent donc
    être picklables (fonction de module, pas de lambda ni de méthode d'objet Qt) ;
  • en deçà de `min_items`, ou si les processus ne peuvent pas démarrer (sandbox, binaire figé
    sans support multiprocessing…), le travail est fait en série : le résultat est le même, seulement
    plus lent ;
  • l'annulation est vérifiée entre deux éléments : ceux déjà lancés se terminent, les autres
    sont abandonnés, puis OperationCancelled est levée.
"""

from __future__ import annotations

import concurrent.futures as cf
import multiprocessing
import os
import threading
from collections.abc import Callable, Sequence
from typing import Any

from . import constants

_POLL_SECONDS = 0.1
_MAX_DEFAULT_WORKERS = 8


def default_workers(cap: int = _MAX_DEFAULT_WORKERS) -> int:
    """Nombre de workers raisonnable : cœurs disponibles (affinité comprise), plafonné."""
    try:
        cpus = len(os.sched_getaffinity(0))       # respecte cgroups / taskset sous Linux
    except (AttributeError, OSError):
        cpus = os.cpu_count() or 2
    return max(1, min(cpus, cap))


def _serial[T, R](fn: Callable[[T], R], items: Sequence[T], on_result: Callable[[int, R], None] | None,
            cancel: Callable[[], bool] | None, start: int = 0,
            results: list | None = None) -> list[R]:
    results = results if results is not None else [None] * len(items)
    for index in range(start, len(items)):
        if cancel is not None and cancel():
            raise constants.OperationCancelled("Opération annulée.")
        if results[index] is None:
            results[index] = fn(items[index])
            if on_result is not None:
                on_result(index, results[index])
    return results


def _run_pool[T, R](executor_factory: Callable[[], cf.Executor], fn: Callable[[T], R], items: Sequence[T],
              on_result: Callable[[int, R], None] | None, cancel: Callable[[], bool] | None) -> list[R]:
    results: list[Any] = [None] * len(items)
    done_flags = [False] * len(items)
    executor = executor_factory()
    futures: dict = {}
    try:
        futures = {executor.submit(fn, item): index for index, item in enumerate(items)}
        pending = set(futures)
        while pending:
            if cancel is not None and cancel():
                for future in pending:
                    future.cancel()
                raise constants.OperationCancelled("Opération annulée.")
            finished, pending = cf.wait(pending, timeout=_POLL_SECONDS, return_when=cf.FIRST_COMPLETED)
            for future in finished:
                index = futures[future]
                results[index] = future.result()          # relance l'exception du worker
                done_flags[index] = True
                if on_result is not None:
                    on_result(index, results[index])
    except BaseException:
        executor.shutdown(wait=True, cancel_futures=True)
        # Les éléments déjà terminés au moment de l'annulation/erreur sont quand même rapportés :
        # l'appelant peut ainsi finir son nettoyage (ex. supprimer l'original d'un fichier chiffré).
        for future, index in futures.items():
            if not done_flags[index] and future.done() and not future.cancelled() and future.exception() is None:
                done_flags[index] = True
                if on_result is not None:
                    on_result(index, future.result())
        raise
    executor.shutdown(wait=True)
    return results


def process_map[T, R](fn: Callable[[T], R], items: Sequence[T], *, workers: int | None = None,
                on_result: Callable[[int, R], None] | None = None,
                cancel: Callable[[], bool] | None = None, min_items: int = 4) -> list[R]:
    """`[fn(x) for x in items]` sur plusieurs processus, résultats dans l'ordre d'entrée.

    `on_result(index, résultat)` est appelé dans le thread appelant, à mesure des terminaisons.
    """
    items = list(items)
    count = workers or default_workers()
    count = min(count, len(items))
    if count <= 1 or len(items) < min_items:
        return _serial(fn, items, on_result, cancel)

    def factory() -> cf.Executor:
        return cf.ProcessPoolExecutor(max_workers=count, mp_context=multiprocessing.get_context("spawn"))

    try:
        return _run_pool(factory, fn, items, on_result, cancel)
    except (OSError, cf.process.BrokenProcessPool, PermissionError, NotImplementedError):
        # Pas de processus disponibles : on refait en série (les fonctions passées sont idempotentes).
        return _serial(fn, items, on_result, cancel)


def thread_map[T, R](fn: Callable[[T], R], items: Sequence[T], *, workers: int | None = None,
               on_result: Callable[[int, R], None] | None = None,
               cancel: Callable[[], bool] | None = None) -> list[R]:
    """Comme process_map mais avec des threads (aucune contrainte de pickle) : pour les E/S."""
    items = list(items)
    count = min(workers or default_workers(), len(items)) if items else 1
    if count <= 1:
        return _serial(fn, items, on_result, cancel)
    return _run_pool(lambda: cf.ThreadPoolExecutor(max_workers=count, thread_name_prefix="voktora"),
                     fn, items, on_result, cancel)


class Counter:
    """Compteur thread-safe pour agréger une progression venant de plusieurs workers."""

    def __init__(self) -> None:
        self._value = 0
        self._lock = threading.Lock()

    def add(self, amount: int) -> int:
        with self._lock:
            self._value += amount
            return self._value

    @property
    def value(self) -> int:
        with self._lock:
            return self._value
