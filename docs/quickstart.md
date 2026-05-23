# Quickstart

```bash
pip install -e .
pybridge generate --bridge examples.basic:bridge --out client/api.ts --hooks
```

## Server

```python
# server.py
from pybridge import Bridge
from pydantic import BaseModel

bridge = Bridge()

class CreateUserInput(BaseModel):
    name: str
    email: str

class User(BaseModel):
    id: str
    name: str
    email: str

@bridge.procedure("users.create")
async def create_user(input: CreateUserInput) -> User: ...

app = bridge.asgi()  # mount under uvicorn, or mount_fastapi(app, bridge)
```

## Client

```ts
// client
import { createClient, type AppRouter } from "./api";
const api = createClient<AppRouter>("http://localhost:8000");
const user = await api.users.create({ name: "Kofi", email: "k@example.com" });
//    ^ fully typed as User
```

## Features

- **Typed procedures** — Pydantic models on input/output flow into TypeScript interfaces automatically.
- **Nested routers** via dot-paths (`users.create`) or `bridge.group("users")`.
- **Three transports out of the box** — HTTP, WebSocket subscriptions (`@bridge.subscription`), and Server-Sent Events streaming (`@bridge.stream`).
- **Middleware + per-request `ctx`** — auth, request-id, anything you can express as `async def mw(ctx, next_)`.
- **Typed errors** — `ProcedureError(code=…)` propagates to the client; declare `errors=("NOT_FOUND",…)` on a procedure to get `@throws PyBridgeError<…>` in the generated JSDoc.
- **File uploads** — declare an `UploadFile` field; the TS client renders it as `File` and switches to multipart automatically.
- **Batch requests** — `/rpc/_batch` collapses many calls into one round-trip.
- **Cookie + CSRF auth helpers** — `cors(...)`, `csrf(...)` ship in `pybridge.security`.
- **Per-procedure `timeout=` and `max_body=`** — production safety nets.
- **Observability hooks** — register an `Observer` for `on_request_start / end / error`; wire OpenTelemetry, Sentry, etc.
- **OpenAPI 3.1 export** + automatic merge into FastAPI's `/docs` and `/redoc`.
- **Framework integrations** — FastAPI (native mount), Django + django-ninja, Sanic, Litestar (via `asgi_dispatch`).
- **React Query hooks** generation with `--hooks`.
- **Plugin system** — register custom Python → TS type mappings via `bridge.register_type(...)`.
- **Codegen** — `pybridge generate` (sub-millisecond on typical schemas) with `--watch` for live regen.

## Watch mode

```bash
pybridge generate --bridge server:bridge --out api.ts --watch
```

Uses [watchfiles](https://github.com/samuelcolvin/watchfiles) (OS events, <10ms latency) when installed (`pip install pybridge[watch]`), otherwise falls back to mtime polling. Editor swap files, `.pyc`, dotfiles, and `__pycache__/` are ignored. SIGINT/SIGTERM shut down cleanly.
