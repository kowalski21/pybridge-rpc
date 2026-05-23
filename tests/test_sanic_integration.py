from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

pytest.importorskip("sanic")


@pytest.mark.asyncio
async def test_sanic_pybridge_dispatch():
    """Sanic + PyBridge composed via asgi_dispatch, driven through ASGI.

    Sanic requires a lifespan startup event before serving requests; we run it
    manually so we don't need uvicorn in the test environment.
    """
    from examples.sanic_mount import application, sanic_app

    # Sanic refuses to serve until it sees an ASGI lifespan startup. Drive one
    # manually against the composed dispatcher so Sanic boots correctly.
    sanic_app.asgi = True
    started = False
    async def receive():
        nonlocal started
        if not started:
            started = True
            return {"type": "lifespan.startup"}
        return {"type": "lifespan.shutdown"}
    async def send(_msg): pass
    import asyncio
    lifespan_task = asyncio.create_task(application({"type": "lifespan"}, receive, send))
    await asyncio.sleep(0.1)  # let startup complete

    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/")
        assert r.status_code == 200
        assert r.json()["app"] == "sanic"

        r = await c.post("/rpc/health.ping")
        assert r.status_code == 200
        assert r.json() == "pong"

        r = await c.post("/rpc/users.create", json={"name": "z", "email": "z@z.z"})
        assert r.status_code == 200
        assert r.json()["name"] == "z"

    lifespan_task.cancel()
    try:
        await lifespan_task
    except (asyncio.CancelledError, Exception):
        pass


def test_asgi_dispatch_unit():
    """Exercise asgi_dispatch with stub apps to verify routing logic."""
    import asyncio
    from pybridge.integrations import asgi_dispatch

    seen = []

    async def app_a(scope, receive, send):
        seen.append(("a", scope["path"]))
    async def app_b(scope, receive, send):
        seen.append(("b", scope["path"]))
    async def app_default(scope, receive, send):
        seen.append(("default", scope["path"]))

    dispatch = asgi_dispatch(
        ("/rpc", app_a),
        ("/ws", app_b),
        default=app_default,
    )

    async def call(path: str):
        await dispatch({"type": "http", "path": path}, None, None)

    asyncio.run(call("/rpc/health.ping"))
    asyncio.run(call("/rpc"))                 # exact match
    asyncio.run(call("/ws"))
    asyncio.run(call("/other"))
    asyncio.run(call("/rpcfoo"))              # NOT under /rpc — must go to default

    assert seen == [
        ("a", "/rpc/health.ping"),
        ("a", "/rpc"),
        ("b", "/ws"),
        ("default", "/other"),
        ("default", "/rpcfoo"),
    ]
