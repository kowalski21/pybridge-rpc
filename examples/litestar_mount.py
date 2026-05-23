"""Run PyBridge alongside Litestar in one ASGI process.

Litestar supports mounting ASGI apps natively, but it strips the mount prefix
before delegating — and PyBridge's internal routes are defined under ``/rpc/*``.
The cleanest composition is therefore the same ``asgi_dispatch`` helper we use
with Sanic: route ``/rpc`` and ``/ws`` to PyBridge, send everything else to
Litestar, and run the composed app under uvicorn.

Run:
    uvicorn examples.litestar_mount:application
"""

from __future__ import annotations

from litestar import Litestar, get

from examples.basic import bridge  # PyBridge with all procedures
from pybridge.integrations import asgi_dispatch


@get("/")
async def home() -> dict:
    return {"app": "litestar"}


@get("/api/version")
async def version() -> dict:
    return {"version": "1.0"}


litestar_app = Litestar(route_handlers=[home, version])

application = asgi_dispatch(
    ("/rpc", bridge.asgi()),
    ("/ws", bridge.asgi()),
    default=litestar_app,
)
