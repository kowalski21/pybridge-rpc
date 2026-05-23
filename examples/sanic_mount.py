"""Run PyBridge alongside Sanic in one ASGI process.

Sanic is its own framework — you don't ``app.mount(...)`` an ASGI app inside it
the way you can with Starlette/FastAPI. Instead we compose at the ASGI layer:
``asgi_dispatch`` sends ``/rpc/*`` and ``/ws`` to PyBridge and lets Sanic
handle everything else.

Run:
    uvicorn examples.sanic_mount:application
"""

from __future__ import annotations

import sanic
from sanic import Sanic
from sanic.response import json as sanic_json

from examples.basic import bridge  # PyBridge with all procedures
from pybridge.integrations import asgi_dispatch


sanic_app = Sanic("DemoApp")


@sanic_app.get("/")
async def home(request):
    return sanic_json({"app": "sanic", "version": sanic.__version__})


@sanic_app.get("/api/version")
async def version(request):
    return sanic_json({"version": "1.0.0"})


# Compose: PyBridge handles /rpc/* and /ws, Sanic handles everything else.
application = asgi_dispatch(
    ("/rpc", bridge.asgi()),
    ("/ws", bridge.asgi()),
    default=sanic_app,
)
