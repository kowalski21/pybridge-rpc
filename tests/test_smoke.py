from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from examples.basic import bridge, app  # noqa: E402
from pybridge.codegen import generate  # noqa: E402
from pybridge.openapi import generate_openapi  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_registry_paths():
    assert set(bridge.procedures) == {
        "users.create",
        "users.get",
        "users.list",
        "users.me",
        "users.upload_avatar",
        "health.ping",
        "ticks.stream",
        "chat.complete",
    }


def test_ping(client):
    r = client.post("/rpc/health.ping")
    assert r.status_code == 200
    assert r.json() == "pong"


def test_create_and_get(client):
    r = client.post("/rpc/users.create", json={"name": "Kofi", "email": "k@example.com"})
    assert r.status_code == 200, r.text
    user = r.json()
    r = client.post("/rpc/users.get", json={"id": user["id"]})
    assert r.status_code == 200
    assert r.json()["email"] == "k@example.com"


def test_not_found_error(client):
    r = client.post("/rpc/users.get", json={"id": "missing"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "NOT_FOUND"


def test_validation_error(client):
    r = client.post("/rpc/users.create", json={"name": "no email"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_INPUT"


def test_middleware_blocks_unauthorized(client):
    r = client.post("/rpc/users.me")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "UNAUTHORIZED"


def test_middleware_allows_authorized(client):
    r = client.post("/rpc/users.me", headers={"authorization": "Bearer x"})
    assert r.status_code == 200, r.text
    assert r.json()["id"] == "u_1"


def test_upload(client):
    files = {"file": ("avatar.png", io.BytesIO(b"PNG-bytes"), "image/png")}
    data = {"__json__": json.dumps({"user_id": "u_1"})}
    r = client.post("/rpc/users.upload_avatar", data=data, files=files)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"user_id": "u_1", "filename": "avatar.png", "size": 9}


def test_batch(client):
    r = client.post(
        "/rpc/_batch",
        json=[
            {"path": "health.ping"},
            {"path": "users.get", "input": {"id": "nope"}},
            {"path": "does.not.exist"},
        ],
    )
    assert r.status_code == 200
    results = r.json()
    assert results[0] == {"result": "pong"}
    assert results[1]["error"]["code"] == "NOT_FOUND"
    assert results[2]["error"]["code"] == "NOT_FOUND"


def test_subscription_via_ws(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "subscribe", "id": "s1", "path": "ticks.stream"})
        msgs = []
        while True:
            msg = ws.receive_json()
            msgs.append(msg)
            if msg["type"] == "complete":
                break
        values = [m["value"] for m in msgs if m["type"] == "next"]
        assert values == [{"n": 0}, {"n": 1}, {"n": 2}]


def test_sse_stream(client):
    with client.stream("POST", "/rpc/chat.complete", json={"prompt": "hello world from sse"}) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        raw = b"".join(r.iter_bytes()).decode()
    # parse SSE
    events = []
    for block in raw.split("\n\n"):
        if not block.strip():
            continue
        ev = {}
        for line in block.split("\n"):
            if line.startswith("event:"):
                ev["event"] = line[6:].strip()
            elif line.startswith("data:"):
                ev["data"] = line[5:].strip()
        events.append(ev)
    nexts = [e["data"] for e in events if e["event"] == "next"]
    assert nexts == ['"hello"', '"world"', '"from"', '"sse"']
    assert events[-1]["event"] == "complete"


def test_sse_stream_validation_error(client):
    with client.stream("POST", "/rpc/chat.complete", json={"wrong_field": 1}) as r:
        assert r.status_code == 200
        raw = b"".join(r.iter_bytes()).decode()
    assert "event: error" in raw
    assert "INVALID_INPUT" in raw


def test_codegen_output():
    ts = generate(bridge, with_hooks=True)
    assert "export interface User" in ts
    assert "export interface CreateUserInput" in ts
    assert "export interface AppRouter" in ts
    assert "create: (input: CreateUserInput) => Promise<User>" in ts
    assert "list: () => Promise<User[]>" in ts
    assert "ping: () => Promise<string>" in ts
    assert "stream: { subscribe:" in ts
    assert "complete: { stream: (input: ChatInput) => Stream<string>" in ts
    assert "export function createClient" in ts
    assert 'file: File' in ts
    assert "createHooks" in ts
    assert 'ProcedureErrors' in ts
    assert '"users.get"' in ts


def test_openapi_export():
    spec = generate_openapi(bridge)
    assert spec["openapi"].startswith("3.")
    assert "/rpc/users.create" in spec["paths"]
    assert "/rpc/health.ping" in spec["paths"]
    # subscriptions excluded
    assert "/rpc/ticks.stream" not in spec["paths"]
    op = spec["paths"]["/rpc/users.create"]["post"]
    assert "requestBody" in op
    assert "responses" in op
