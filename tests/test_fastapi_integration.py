from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from examples.basic import bridge  # noqa: E402
from pybridge.integrations import mount_fastapi  # noqa: E402


def test_merge_into_root_openapi():
    app = FastAPI(title="MyApp", version="2.3.4")

    @app.get("/api/version")
    async def version() -> dict:
        return {"v": "1"}

    mount_fastapi(app, bridge)
    spec = TestClient(app).get("/openapi.json").json()

    # FastAPI's own route still there
    assert "/api/version" in spec["paths"]
    # PyBridge procedures merged
    assert "/rpc/users.create" in spec["paths"]
    assert "/rpc/health.ping" in spec["paths"]
    # Subscriptions excluded (HTTP-only spec)
    assert "/rpc/ticks.stream" not in spec["paths"]
    # Schemas merged
    assert "User" in spec["components"]["schemas"]
    # FastAPI's metadata preserved
    assert spec["info"]["title"] == "MyApp"
    assert spec["info"]["version"] == "2.3.4"


def test_merge_under_prefix():
    app = FastAPI()
    mount_fastapi(app, bridge, prefix="/api")
    spec = TestClient(app).get("/openapi.json").json()
    assert "/api/rpc/users.create" in spec["paths"]
    assert "/rpc/users.create" not in spec["paths"]


def test_opt_out_of_merge():
    app = FastAPI()
    mount_fastapi(app, bridge, include_in_schema=False)
    spec = TestClient(app).get("/openapi.json").json()
    assert all(not p.startswith("/rpc/") for p in spec["paths"])


def test_starlette_app_not_patched():
    """Plain Starlette has no .openapi; mount should still succeed."""
    from starlette.applications import Starlette

    app = Starlette()
    # Should not raise even though include_in_schema defaults to True
    mount_fastapi(app, bridge)
    client = TestClient(app)
    assert client.post("/rpc/health.ping").status_code == 200
