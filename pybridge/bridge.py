from __future__ import annotations

import inspect
import typing as t
from dataclasses import dataclass, field

from .context import Context


Middleware = t.Callable[[Context, t.Callable], t.Awaitable[t.Any]]


@dataclass
class Procedure:
    path: str
    handler: t.Callable
    input_type: type | None
    output_type: type | None
    is_async: bool
    middlewares: list[Middleware] = field(default_factory=list)
    wants_ctx: bool = False
    error_codes: tuple[str, ...] = ()
    kind: str = "procedure"  # or "subscription" / "stream"
    timeout: float | None = None
    max_body: int | None = None
    description: str | None = None


@dataclass
class Bridge:
    procedures: dict[str, Procedure] = field(default_factory=dict)
    global_middlewares: list[Middleware] = field(default_factory=list)
    type_overrides: dict[type, str] = field(default_factory=dict)
    observers: list[t.Any] = field(default_factory=list)
    connect_handlers: list[t.Callable] = field(default_factory=list)

    def observer(self, obs):
        """Register an Observer (instance or class — instances are constructed lazily)."""
        self.observers.append(obs() if isinstance(obs, type) else obs)
        return obs

    def on_connect(self, fn: t.Callable):
        """Register a handler that runs once per WebSocket connection, before
        any subscribe message is processed. Use it for one-shot auth: the
        handler's ``ctx.state`` is inherited by every subscription on the same
        socket, so a DB lookup happens once instead of per message.

        Raise ``ProcedureError`` from the handler to reject the connection;
        the WS is closed with code 1008 (policy violation).
        """
        self.connect_handlers.append(fn)
        return fn

    def procedure(
        self,
        path: str,
        *,
        middlewares: list[Middleware] | None = None,
        errors: t.Iterable[str] = (),
        timeout: float | None = None,
        max_body: int | None = None,
    ) -> t.Callable:
        return _register(
            self, path, middlewares or [], tuple(errors),
            kind="procedure", timeout=timeout, max_body=max_body,
        )

    def subscription(
        self,
        path: str,
        *,
        middlewares: list[Middleware] | None = None,
    ) -> t.Callable:
        return _register(self, path, middlewares or [], (), kind="subscription")

    def stream(
        self,
        path: str,
        *,
        middlewares: list[Middleware] | None = None,
        errors: t.Iterable[str] = (),
        max_body: int | None = None,
    ) -> t.Callable:
        """HTTP / Server-Sent Events streaming procedure.

        Same shape as ``@procedure`` but the handler is an async generator
        whose yielded values are streamed to the client as SSE events.
        """
        return _register(
            self, path, middlewares or [], tuple(errors),
            kind="stream", max_body=max_body,
        )

    def middleware(self, fn: Middleware) -> Middleware:
        self.global_middlewares.append(fn)
        return fn

    def group(self, prefix: str) -> "Group":
        return Group(self, prefix)

    def register_type(self, py_type: type, ts: str) -> None:
        """Register a custom Python -> TypeScript type mapping (plugin hook)."""
        self.type_overrides[py_type] = ts

    def asgi(self, middleware: list | None = None):
        from .transport import build_asgi
        return build_asgi(self, middleware=middleware)


@dataclass
class Group:
    _bridge: Bridge
    _prefix: str

    def procedure(
        self,
        path: str,
        *,
        middlewares: list[Middleware] | None = None,
        errors: t.Iterable[str] = (),
    ) -> t.Callable:
        return _register(
            self._bridge,
            f"{self._prefix}.{path}",
            middlewares or [],
            tuple(errors),
            kind="procedure",
        )

    def subscription(
        self,
        path: str,
        *,
        middlewares: list[Middleware] | None = None,
    ) -> t.Callable:
        return _register(self._bridge, f"{self._prefix}.{path}", middlewares or [], (), kind="subscription")

    def stream(
        self,
        path: str,
        *,
        middlewares: list[Middleware] | None = None,
        errors: t.Iterable[str] = (),
    ) -> t.Callable:
        return _register(
            self._bridge,
            f"{self._prefix}.{path}",
            middlewares or [],
            tuple(errors),
            kind="stream",
        )

    def group(self, prefix: str) -> "Group":
        return Group(self._bridge, f"{self._prefix}.{prefix}")


def _register(
    bridge: Bridge,
    path: str,
    middlewares: list[Middleware],
    errors: tuple[str, ...],
    kind: str,
    timeout: float | None = None,
    max_body: int | None = None,
) -> t.Callable:
    def decorator(fn: t.Callable) -> t.Callable:
        if path in bridge.procedures:
            raise ValueError(f"procedure {path!r} already registered")
        input_type, output_type, wants_ctx = _extract_signature(fn, kind)
        bridge.procedures[path] = Procedure(
            path=path,
            handler=fn,
            input_type=input_type,
            output_type=output_type,
            is_async=inspect.iscoroutinefunction(fn) or inspect.isasyncgenfunction(fn),
            middlewares=list(middlewares),
            wants_ctx=wants_ctx,
            error_codes=errors,
            kind=kind,
            timeout=timeout,
            max_body=max_body,
            description=(fn.__doc__ or "").strip() or None,
        )
        return fn
    return decorator


def _extract_signature(fn: t.Callable, kind: str) -> tuple[type | None, type | None, bool]:
    hints = t.get_type_hints(fn)
    return_type = hints.pop("return", None)
    if kind in {"subscription", "stream"} and return_type is not None:
        return_type = _strip_async_iterator(return_type)
    sig = inspect.signature(fn)
    input_type: type | None = None
    wants_ctx = False
    for name in sig.parameters:
        if name == "ctx":
            wants_ctx = True
            continue
        if name in hints and input_type is None:
            input_type = hints[name]
    return input_type, return_type, wants_ctx


def _strip_async_iterator(tp: t.Any) -> t.Any:
    origin = t.get_origin(tp)
    if origin in (
        t.AsyncIterator,
        t.AsyncGenerator,
    ) or (origin is not None and getattr(origin, "__name__", "") in {"AsyncIterator", "AsyncGenerator"}):
        args = t.get_args(tp)
        if args:
            return args[0]
    return tp
