"""WebSocket auth with @bridge.on_connect.

Auth runs once per WebSocket connection — not per subscribe message — so a
DB lookup / token verification happens exactly once even if the client opens
many subscriptions on the same socket.

Run:
    uvicorn examples.ws_auth:app
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from pydantic import BaseModel

from pybridge import Bridge, Context, ProcedureError


bridge = Bridge()

# Demo "user database". In production: query your DB / verify a JWT.
_TOKENS = {
    "tok_alice": {"id": "u_1", "name": "Alice"},
    "tok_bob":   {"id": "u_2", "name": "Bob"},
}


@bridge.on_connect
async def authenticate(ctx: Context):
    """Runs once on WS handshake. Raise ProcedureError to reject the connection.

    Accepts the token from either:
      - Authorization: Bearer <token>          (Node / server-to-server clients)
      - ?token=<token>  on the WS URL          (browser clients — browsers
        cannot set arbitrary WS headers, so the query-string is the standard
        workaround. Same-origin cookies also flow automatically.)
    """
    token = ctx.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not token:
        # ctx.request is the Starlette WebSocket here
        token = ctx.request.query_params.get("token", "")
    user = _TOKENS.get(token)
    if user is None:
        raise ProcedureError(code="UNAUTHORIZED", message="invalid or missing token")
    ctx.user = user                # available to every subscription on this socket
    print(f"[ws] connected: {user['name']} ({user['id']})")


# ---------------------------------------------------------------------------
# Subscriptions — none of them re-check auth; they read ctx.user
# ---------------------------------------------------------------------------


class Notification(BaseModel):
    to_user: str
    body: str


@bridge.subscription("notifications.stream")
async def notifications(ctx: Context) -> AsyncIterator[Notification]:
    """Push notifications scoped to the connected user."""
    for i in range(3):
        await asyncio.sleep(0.1)
        yield Notification(to_user=ctx.user["id"], body=f"hello {ctx.user['name']} #{i}")


class Tick(BaseModel):
    user: str
    n: int


@bridge.subscription("ticks.stream")
async def ticks(ctx: Context) -> AsyncIterator[Tick]:
    """A second subscription that shares the same auth state — no re-auth."""
    for i in range(5):
        await asyncio.sleep(0.05)
        yield Tick(user=ctx.user["id"], n=i)


app = bridge.asgi()


# ---------------------------------------------------------------------------
# Client side — pass the token at WS handshake time via the `wsFactory` option.
#
# Browser (query-string, since browsers can't set arbitrary WS headers):
#
#     const api = createClient<AppRouter>("http://localhost:8000", {
#       wsFactory: (url) => {
#         const u = new URL(url);
#         u.searchParams.set("token", localStorage.getItem("token") ?? "");
#         return new WebSocket(u.toString());
#       },
#     });
#
# Node / Bun / Deno (real headers via the `ws` package):
#
#     import WebSocket from "ws";
#     const api = createClient<AppRouter>("http://localhost:8000", {
#       wsFactory: (url) =>
#         new WebSocket(url, { headers: { authorization: `Bearer ${TOKEN}` } }) as any,
#     });
#
# Usage on either runtime is identical:
#     const sub = api.notifications.stream.subscribe();
#     for await (const n of sub) console.log(n.body);
# ---------------------------------------------------------------------------
