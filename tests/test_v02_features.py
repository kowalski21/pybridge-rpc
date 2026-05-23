"""Tests for the v0.2 batch: docstrings → JSDoc, typed errors, limits, observers."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from pydantic import BaseModel
from starlette.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pybridge import Bridge, ProcedureError  # noqa: E402
from pybridge.codegen import generate  # noqa: E402
from pybridge.observability import RequestEvent  # noqa: E402


class Echo(BaseModel):
    msg: str


def _bridge_with_features() -> Bridge:
    b = Bridge()

    @b.procedure("docs.demo")
    async def doc_demo(input: Echo) -> str:
        """Returns whatever you send in.

        Useful for sanity checks.
        """
        return input.msg

    @b.procedure("limits.timeout", timeout=0.05)
    async def slow() -> str:
        await asyncio.sleep(0.5)
        return "never"

    @b.procedure("limits.maxbody", max_body=10)
    async def small(input: Echo) -> str:
        return input.msg

    @b.procedure("errs.coded", errors=("NOT_FOUND", "FORBIDDEN"))
    async def coded(input: Echo) -> str:
        if input.msg == "miss":
            raise ProcedureError(code="NOT_FOUND", message="nope")
        return input.msg

    return b


def test_docstring_renders_as_jsdoc():
    ts = generate(_bridge_with_features())
    # Multi-line docstring → JSDoc block; single-line + @throws merged
    assert "/**" in ts and "Returns whatever you send in." in ts
    assert "@throws PyBridgeError<\"NOT_FOUND\" | \"FORBIDDEN\">" in ts


def test_pybridge_error_is_generic():
    ts = generate(_bridge_with_features())
    assert "PyBridgeError<Code extends string = string>" in ts


def test_per_procedure_timeout():
    client = TestClient(_bridge_with_features().asgi())
    r = client.post("/rpc/limits.timeout")
    assert r.status_code == 504
    assert r.json()["error"]["code"] == "TIMEOUT"


def test_per_procedure_max_body():
    client = TestClient(_bridge_with_features().asgi())
    big = {"msg": "a" * 1000}
    r = client.post("/rpc/limits.maxbody", json=big)
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_observers_fire_on_success_and_error():
    b = _bridge_with_features()
    events: list[tuple[str, RequestEvent]] = []

    @b.observer
    class _Obs:
        async def on_request_start(self, ev): events.append(("start", ev))
        async def on_request_end(self, ev):   events.append(("end", ev))
        async def on_error(self, ev):         events.append(("error", ev))

    client = TestClient(b.asgi())
    assert client.post("/rpc/docs.demo", json={"msg": "hi"}).status_code == 200
    assert client.post("/rpc/errs.coded", json={"msg": "miss"}).status_code == 400

    kinds = [k for k, _ in events]
    assert kinds == ["start", "end", "start", "error"]
    assert events[1][1].duration_ms is not None
    assert events[3][1].code == "NOT_FOUND"


def test_failing_observer_does_not_break_request():
    b = _bridge_with_features()

    @b.observer
    class _Bad:
        async def on_request_start(self, ev):
            raise RuntimeError("boom")

    client = TestClient(b.asgi())
    r = client.post("/rpc/docs.demo", json={"msg": "still works"})
    assert r.status_code == 200
    assert r.json() == "still works"
