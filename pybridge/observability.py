"""Pluggable observability hook interface.

Wire OpenTelemetry, Sentry, Datadog, structlog, etc. by registering an
``Observer`` on the bridge::

    @bridge.observer
    class LogObserver:
        async def on_request_start(self, ev): print("->", ev.path)
        async def on_request_end(self, ev):   print("<-", ev.path, ev.duration_ms, "ms")
        async def on_error(self, ev):         print("!!", ev.path, ev.code)

All callbacks are optional. Hooks run in registration order; raised exceptions
are caught and never affect the procedure result.
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass, field


@dataclass
class RequestEvent:
    path: str
    kind: str                              # "procedure" | "stream" | "subscription"
    headers: dict[str, str] = field(default_factory=dict)
    state: dict[str, t.Any] = field(default_factory=dict)
    duration_ms: float | None = None       # set on on_request_end / on_error
    code: str | None = None                # set on on_error
    exception: BaseException | None = None # set on on_error


class Observer(t.Protocol):
    async def on_request_start(self, ev: RequestEvent) -> None: ...
    async def on_request_end(self, ev: RequestEvent) -> None: ...
    async def on_error(self, ev: RequestEvent) -> None: ...
