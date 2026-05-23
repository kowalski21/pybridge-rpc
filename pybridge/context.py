from __future__ import annotations

import typing as t
from dataclasses import dataclass, field


@dataclass
class Context:
    """Per-call context passed to middleware and handlers that declare a `ctx` parameter."""

    path: str
    headers: dict[str, str] = field(default_factory=dict)
    state: dict[str, t.Any] = field(default_factory=dict)
    request: t.Any = None  # Starlette Request, when transported over HTTP

    def __getattr__(self, name: str) -> t.Any:
        # Convenience: ctx.user instead of ctx.state["user"], when middleware sets it.
        if name.startswith("_"):
            raise AttributeError(name)
        state = self.__dict__.get("state", {})
        if name in state:
            return state[name]
        raise AttributeError(name)

    def __setattr__(self, name: str, value: t.Any) -> None:
        if name in {"path", "headers", "state", "request"}:
            object.__setattr__(self, name, value)
        else:
            self.state[name] = value
