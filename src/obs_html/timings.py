"""Exclusive per-stage wall-clock durations for ``--timings``.

``STAGES`` is the one list of build stages; help, output and baselines read it.
Owners mark their work with ``stage(name)``; it costs nothing unless a ``recording()``
is active. A nested stage pauses its enclosing stage, so durations never overlap.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from time import perf_counter
from typing import Iterator

STAGES: dict[str, str] = {
    "parse": "configuration, manifest, notes",
    "producers": "silent cmd fences, before conversion",
    "provenance": "git",
    "render": "HTML projection",
    "figures": "figure fences",
    "commands": "cmd fences",
    "source-archive": "--embed-source",
    "write": "output file",
    "open": "--check-rendered loading",
    "print": "PDF printing",
    "attach": "PDF source attachment",
}


class Timings:
    def __init__(self) -> None:
        self.durations: dict[str, float] = {}
        self._open: list[list] = []

    def add(self, name: str, seconds: float) -> None:
        self.durations[name] = self.durations.get(name, 0.0) + seconds

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        now = perf_counter()
        if self._open:
            enclosing = self._open[-1]
            self.add(enclosing[0], now - enclosing[1])
        self._open.append([name, now])
        try:
            yield
        finally:
            now = perf_counter()
            self.add(name, now - self._open.pop()[1])
            if self._open:
                self._open[-1][1] = now


_active: ContextVar[Timings | None] = ContextVar("obs_html_timings", default=None)


@contextmanager
def recording() -> Iterator[Timings]:
    timings = Timings()
    token = _active.set(timings)
    try:
        yield timings
    finally:
        _active.reset(token)


@contextmanager
def stage(name: str) -> Iterator[None]:
    if name not in STAGES:
        raise ValueError(f"Unregistered build stage: {name}")
    timings = _active.get()
    if timings is None:
        yield
        return
    with timings.stage(name):
        yield
