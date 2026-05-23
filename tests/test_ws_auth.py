"""WebSocket connect-time auth, per-connection state, and observer parity."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pybridge import Bridge, Context, ProcedureError  # noqa: E402
from pybridge.observability import RequestEvent  # noqa: E402


def _bridge_with_auth_sub():
    """Bridge with: an on_connect auth handler, two subscriptions, and an observer."""
    b = Bridge()
    auth_calls = {"n": 0}

    @b.on_connect
    async def authenticate(ctx: Context):
        auth_calls["n"] += 1
        token = ctx.headers.get("authorization", "")
        if not token.startswith("Bearer "):
            raise ProcedureError(code="UNAUTHORIZED", message="missing or bad token")
        # Stash on conn_ctx — inherited by every subscription on this socket.
        ctx.user_id = token.removeprefix("Bearer ")

    @b.subscription("a.stream")
    async def stream_a(ctx: Context):
        # Pulls user_id from connection state — no auth re-check
        yield {"who": ctx.user_id, "n": 0}
        yield {"who": ctx.user_id, "n": 1}

    @b.subscription("b.stream")
    async def stream_b(ctx: Context):
        yield {"who": ctx.user_id, "src": "b"}

    return b, auth_calls


def test_ws_connect_rejects_without_token():
    b, _ = _bridge_with_auth_sub()
    client = TestClient(b.asgi())
    with pytest.raises(Exception):  # websocket closes with 1008 — TestClient raises
        with client.websocket_connect("/ws"):
            pass


def test_ws_connect_rejection_carries_reason():
    b, _ = _bridge_with_auth_sub()
    client = TestClient(b.asgi())
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # forces the close to be observed
    assert exc_info.value.code == 1008
    assert "missing or bad token" in exc_info.value.reason


def test_ws_auth_runs_once_per_connection():
    b, calls = _bridge_with_auth_sub()
    client = TestClient(b.asgi())
    with client.websocket_connect("/ws", headers={"authorization": "Bearer alice"}) as ws:
        # Subscribe three times to two different procedures
        for sid, path in [("1", "a.stream"), ("2", "b.stream"), ("3", "a.stream")]:
            ws.send_json({"type": "subscribe", "id": sid, "path": path})
            while True:
                m = ws.receive_json()
                if m["type"] == "complete":
                    break
    assert calls["n"] == 1  # exactly one auth handler invocation per connection


def test_subscription_inherits_connection_state():
    b, _ = _bridge_with_auth_sub()
    client = TestClient(b.asgi())
    with client.websocket_connect("/ws", headers={"authorization": "Bearer kofi"}) as ws:
        ws.send_json({"type": "subscribe", "id": "1", "path": "a.stream"})
        msgs = []
        while True:
            m = ws.receive_json()
            msgs.append(m)
            if m["type"] == "complete":
                break
    values = [m["value"] for m in msgs if m["type"] == "next"]
    assert values == [{"who": "kofi", "n": 0}, {"who": "kofi", "n": 1}]


def test_observer_fires_for_ws_connect_and_subscription():
    b, _ = _bridge_with_auth_sub()
    events: list[tuple[str, RequestEvent]] = []

    @b.observer
    class _Obs:
        async def on_request_start(self, ev): events.append(("start", ev))
        async def on_request_end(self, ev):   events.append(("end", ev))
        async def on_error(self, ev):         events.append(("error", ev))

    client = TestClient(b.asgi())
    # 1) Rejected connection: connect start + connect error
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()

    # 2) Successful connection with one subscribe: connect start + sub start/end + connect end
    with client.websocket_connect("/ws", headers={"authorization": "Bearer x"}) as ws:
        ws.send_json({"type": "subscribe", "id": "1", "path": "a.stream"})
        while True:
            m = ws.receive_json()
            if m["type"] == "complete":
                break

    kinds = [k for k, _ in events]
    # rejected leg: start, error
    assert kinds[:2] == ["start", "error"]
    # accepted leg: start (connect), start (sub), end (sub), end (connect)
    assert kinds[2:] == ["start", "start", "end", "end"]
    # error event carried the right code
    assert events[1][1].code == "UNAUTHORIZED"
    # subscription event was tagged correctly
    sub_event = events[3][1]
    assert sub_event.kind == "subscription"
    assert sub_event.path == "a.stream"
