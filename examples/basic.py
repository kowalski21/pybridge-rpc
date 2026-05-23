from __future__ import annotations

import asyncio
from typing import AsyncIterator
from uuid import uuid4

from pydantic import BaseModel

from pybridge import Bridge, Context, ProcedureError, UploadFile


bridge = Bridge()

_DB: dict[str, dict] = {}


class CreateUserInput(BaseModel):
    name: str
    email: str
    age: int | None = None


class GetUserInput(BaseModel):
    id: str


class User(BaseModel):
    id: str
    name: str
    email: str
    age: int | None = None


class AvatarUpload(BaseModel):
    user_id: str
    file: UploadFile

    model_config = {"arbitrary_types_allowed": True}


@bridge.middleware
async def request_id(ctx: Context, next_):
    ctx.request_id = ctx.headers.get("x-request-id", uuid4().hex)
    return await next_(ctx)


async def require_auth(ctx: Context, next_):
    if not ctx.headers.get("authorization"):
        raise ProcedureError(code="UNAUTHORIZED", message="missing token")
    ctx.user = {"id": "u_1"}
    return await next_(ctx)


users = bridge.group("users")


@users.procedure("create")
async def create_user(input: CreateUserInput) -> User:
    user = User(id=uuid4().hex, **input.model_dump())
    _DB[user.id] = user.model_dump()
    return user


@users.procedure("get", errors=("NOT_FOUND",))
async def get_user(input: GetUserInput) -> User:
    row = _DB.get(input.id)
    if row is None:
        raise ProcedureError(code="NOT_FOUND", message="User not found")
    return User(**row)


@users.procedure("list")
async def list_users() -> list[User]:
    return [User(**row) for row in _DB.values()]


@users.procedure("me", middlewares=[require_auth])
async def me(ctx: Context) -> User:
    return User(id=ctx.user["id"], name="me", email="me@example.com")


@users.procedure("upload_avatar")
async def upload_avatar(input: AvatarUpload) -> dict:
    return {"user_id": input.user_id, "filename": input.file.filename, "size": len(input.file)}


@bridge.procedure("health.ping")
async def ping() -> str:
    return "pong"


@bridge.subscription("ticks.stream")
async def stream_ticks():
    for i in range(3):
        await asyncio.sleep(0)
        yield {"n": i}


class ChatInput(BaseModel):
    prompt: str


@bridge.stream("chat.complete")
async def chat_complete(input: ChatInput) -> AsyncIterator[str]:
    """Token-by-token streaming over SSE (think LLM completions)."""
    for token in input.prompt.split():
        await asyncio.sleep(0)
        yield token


app = bridge.asgi()
