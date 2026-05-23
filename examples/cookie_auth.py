"""Cookie-based session auth with CSRF protection.

Run:
    uvicorn examples.cookie_auth:app --reload

Procedures:
    auth.login   -> sets HttpOnly session cookie
    auth.logout  -> clears session cookie
    auth.me      -> requires session, returns current user
    notes.create -> requires session
    notes.list   -> requires session

Generate the typed client:
    pybridge generate --bridge examples.cookie_auth:bridge --out client/api.ts
"""

from __future__ import annotations

import secrets
from uuid import uuid4

from pydantic import BaseModel
from starlette.requests import Request

from pybridge import Bridge, Context, ProcedureError
from pybridge.security import cors, csrf


bridge = Bridge()

# Demo "database" + session store. In production: real DB + Redis/etc.
_USERS = {"alice@example.com": {"id": "u_1", "name": "Alice", "password": "hunter2"}}
_SESSIONS: dict[str, str] = {}  # session_id -> user_id
_NOTES: dict[str, list[dict]] = {}  # user_id -> [{id, text}]

SESSION_COOKIE = "pyb_session"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class LoginInput(BaseModel):
    email: str
    password: str


class User(BaseModel):
    id: str
    name: str
    email: str


class CreateNote(BaseModel):
    text: str


class Note(BaseModel):
    id: str
    text: str


# ---------------------------------------------------------------------------
# Middleware: load the session from the cookie into ctx
# ---------------------------------------------------------------------------


@bridge.middleware
async def load_session(ctx: Context, next_):
    request: Request | None = ctx.request
    sid = request.cookies.get(SESSION_COOKIE) if request else None
    ctx.user_id = _SESSIONS.get(sid) if sid else None
    return await next_(ctx)


async def require_user(ctx: Context, next_):
    if not ctx.user_id:
        raise ProcedureError(code="UNAUTHORIZED", message="Not signed in")
    return await next_(ctx)


# ---------------------------------------------------------------------------
# auth.*
# ---------------------------------------------------------------------------

auth = bridge.group("auth")


@auth.procedure("login")
async def login(input: LoginInput, ctx: Context) -> User:
    row = _USERS.get(input.email)
    if not row or row["password"] != input.password:
        raise ProcedureError(code="INVALID_CREDENTIALS", message="Bad email or password")
    sid = secrets.token_urlsafe(32)
    _SESSIONS[sid] = row["id"]
    # Set the session cookie on the outgoing response. The PyBridge handler
    # gives back the model; we attach the cookie via request.scope["set_cookies"]
    # using Starlette's mutable response chain (see end of file).
    ctx.set_cookies = [(SESSION_COOKIE, sid)]
    return User(id=row["id"], name=row["name"], email=input.email)


@auth.procedure("logout", middlewares=[require_user])
async def logout(ctx: Context) -> dict:
    request: Request | None = ctx.request
    sid = request.cookies.get(SESSION_COOKIE) if request else None
    if sid:
        _SESSIONS.pop(sid, None)
    ctx.clear_cookies = [SESSION_COOKIE]
    return {"ok": True}


@auth.procedure("me", middlewares=[require_user])
async def me(ctx: Context) -> User:
    row = next(u for u in _USERS.values() if u["id"] == ctx.user_id)
    return User(id=row["id"], name=row["name"], email=next(e for e, u in _USERS.items() if u["id"] == ctx.user_id))


# ---------------------------------------------------------------------------
# notes.*  (all require auth)
# ---------------------------------------------------------------------------

notes = bridge.group("notes")


@notes.procedure("create", middlewares=[require_user])
async def create_note(input: CreateNote, ctx: Context) -> Note:
    note = {"id": uuid4().hex, "text": input.text}
    _NOTES.setdefault(ctx.user_id, []).append(note)
    return Note(**note)


@notes.procedure("list", middlewares=[require_user])
async def list_notes(ctx: Context) -> list[Note]:
    return [Note(**n) for n in _NOTES.get(ctx.user_id, [])]


# ---------------------------------------------------------------------------
# Cookie-side-effects middleware: a small middleware that runs LAST on the way
# out and copies ctx.set_cookies / ctx.clear_cookies onto the Starlette
# response. Lives here so the example is self-contained.
# ---------------------------------------------------------------------------


from starlette.middleware.base import BaseHTTPMiddleware


class _CookieEffects(BaseHTTPMiddleware):
    """Reads cookie hints stashed on the Starlette request scope and applies
    them to the response. PyBridge handlers can't set cookies directly because
    they return plain values, not Response objects — so they stash hints on
    ``ctx`` and we read them here.

    To keep the example tiny, we use ``request.state`` as the shared channel.
    """

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        for name, value in getattr(request.state, "set_cookies", []) or []:
            response.set_cookie(name, value, httponly=True, samesite="lax", path="/")
        for name in getattr(request.state, "clear_cookies", []) or []:
            response.delete_cookie(name, path="/")
        return response


# Bridge the Context's set_cookies/clear_cookies onto request.state so the
# middleware above can see them. This runs after the handler.
@bridge.middleware
async def _commit_cookies(ctx: Context, next_):
    try:
        return await next_(ctx)
    finally:
        if ctx.request is not None:
            ctx.request.state.set_cookies = ctx.state.get("set_cookies")
            ctx.request.state.clear_cookies = ctx.state.get("clear_cookies")


from starlette.middleware import Middleware

app = bridge.asgi(middleware=[
    cors(origins=["http://localhost:5173"], credentials=True),
    csrf(cookie_name="pyb_csrf"),
    Middleware(_CookieEffects),
])
