from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

pytest.importorskip("litestar")


@pytest.mark.asyncio
async def test_litestar_pybridge_dispatch():
    """Litestar + PyBridge composed via asgi_dispatch."""
    from examples.litestar_mount import application

    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        # Litestar route
        r = await c.get("/")
        assert r.status_code == 200
        assert r.json()["app"] == "litestar"

        r = await c.get("/api/version")
        assert r.status_code == 200

        # Litestar's own OpenAPI schema still works
        r = await c.get("/schema/openapi.json")
        assert r.status_code == 200
        assert "/api/version" in r.json()["paths"]

        # PyBridge through the same composed ASGI app
        r = await c.post("/rpc/health.ping")
        assert r.status_code == 200
        assert r.json() == "pong"

        r = await c.post("/rpc/users.create", json={"name": "z", "email": "z@z.z"})
        assert r.status_code == 200
        assert r.json()["name"] == "z"
