from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import BaseModel
from starlette.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pybridge import Bridge  # noqa: E402
from pybridge.security import cors, csrf  # noqa: E402
from pybridge.codegen import generate  # noqa: E402


class Echo(BaseModel):
    msg: str


def make_bridge() -> Bridge:
    b = Bridge()

    @b.procedure("echo")
    async def echo(input: Echo) -> str:
        return input.msg

    return b


def test_cors_rejects_credentials_with_wildcard():
    with pytest.raises(ValueError):
        cors(origins="*", credentials=True)


def test_cors_sets_credentialed_headers():
    b = make_bridge()
    app = b.asgi(middleware=[cors(origins=["http://app.example"], credentials=True)])
    client = TestClient(app)
    r = client.options(
        "/rpc/echo",
        headers={
            "origin": "http://app.example",
            "access-control-request-method": "POST",
        },
    )
    assert r.headers.get("access-control-allow-origin") == "http://app.example"
    assert r.headers.get("access-control-allow-credentials") == "true"


def test_csrf_rejects_request_without_token():
    b = make_bridge()
    app = b.asgi(middleware=[csrf()])
    client = TestClient(app)
    r = client.post("/rpc/echo", json={"msg": "hi"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "CSRF_FAILED"
    # cookie was still issued so the next call can succeed
    assert "pyb_csrf" in r.cookies


def test_csrf_passes_when_token_matches():
    b = make_bridge()
    app = b.asgi(middleware=[csrf()])
    client = TestClient(app)
    seed = client.post("/rpc/echo", json={"msg": "x"})
    token = seed.cookies["pyb_csrf"]

    r = client.post("/rpc/echo", json={"msg": "ok"}, headers={"x-csrf-token": token})
    assert r.status_code == 200
    assert r.json() == "ok"


def test_csrf_rejects_mismatched_token():
    b = make_bridge()
    app = b.asgi(middleware=[csrf()])
    client = TestClient(app)
    client.post("/rpc/echo", json={"msg": "x"})  # seed cookie
    r = client.post("/rpc/echo", json={"msg": "ok"}, headers={"x-csrf-token": "wrong"})
    assert r.status_code == 403


def test_generated_client_exposes_credentials_and_csrf():
    ts = generate(make_bridge())
    assert "credentials?: RequestCredentials" in ts
    assert "csrfCookie?: string" in ts
    assert 'headers["x-csrf-token"] = csrf' in ts
    assert "credentials: opts.credentials" in ts
