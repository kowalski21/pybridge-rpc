# PyBridge

[![PyPI version](https://img.shields.io/pypi/v/pybridge-rpc.svg)](https://pypi.org/project/pybridge-rpc/)
[![Python versions](https://img.shields.io/pypi/pyversions/pybridge-rpc.svg)](https://pypi.org/project/pybridge-rpc/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](./LICENSE)
[![Status: Beta](https://img.shields.io/badge/status-beta-orange.svg)](#status)

End-to-end type safety from Python to TypeScript — no codegen ceremony, no schema drift.

Define procedures in Python with standard type hints + Pydantic. Run one command. Get a fully typed TypeScript client.

```bash
pip install pybridge-rpc
pybridge generate --bridge examples.basic:bridge --out client/api.ts --hooks
```

```python
# server.py
from pybridge import Bridge
from pydantic import BaseModel

bridge = Bridge()

class User(BaseModel):
    id: str
    name: str
    email: str

@bridge.procedure("users.create")
async def create_user(input: User) -> User: ...

app = bridge.asgi()
```

```ts
import { createClient, type AppRouter } from "./api";
const api = createClient<AppRouter>("http://localhost:8000");
const user = await api.users.create({ id: "1", name: "Kofi", email: "k@example.com" });
//    ^ fully typed as User
```

## Features

- **Zero-ceremony typed RPC** — Python function signature *is* the API contract. No `.input()/.output()` wrappers, no separate schema files.
- **Pydantic → TypeScript** — full type projection: nested models, unions, literals, enums, `datetime`, `UUID`, tuples, `dict`, optional/nullable.
- **One-command codegen** — `pybridge generate` emits a single `api.ts` with types + proxy client + optional TanStack Query hooks.
- **ASGI transport** — HTTP, WebSocket **subscriptions**, and **SSE streams** out of the box (built on Starlette).
- **Framework integrations** — drop into FastAPI, Django, Sanic, or Litestar without rewriting your app.
- **File uploads, CORS & CSRF helpers, observer protocol** for logging/metrics/tracing hooks.
- **OpenAPI 3.x exporter** — get a spec for tooling that needs one, without making it the source of truth.
- **Watch mode** — `watchfiles`-backed regeneration with mtime-polling fallback.
- **Typed errors** — `ProcedureError` codes propagate to the client.
- **Fully typed package** — ships `py.typed`.

## Why PyBridge

Full-stack teams with a Python backend and a TypeScript frontend live with a constant gap: define models in Pydantic, redefine them as TS interfaces, hope they stay in sync. The usual fixes have rough edges:

| Approach | Trade-off |
|---|---|
| **FastAPI + openapi-typescript** | Works, but it's a 4-step pipeline (FastAPI → OpenAPI → codegen → wire-up). Generated SDKs have opinions about method names and return shapes that often need wrapping. |
| **tRPC / oRPC** | Great DX — but your backend has to be TypeScript. |
| **GraphQL + codegen** | Adds a schema language, a runtime, and a resolver layer for something a function signature already encodes. |
| **PyBridge** | Python type hints are the source of truth. One command produces a thin, idiomatic TS client whose types are a direct projection of your Pydantic models. |

The goal is the same DX tRPC/oRPC developers enjoy — with Python as the source of truth. See [docs/design.md](./docs/design.md) for the full rationale.

## Status

Phases 1–3 are complete and tested (33 tests passing). Currently `0.2.x` — beta. API is stable for the documented surface; breaking changes will be called out in release notes.

## Documentation

All docs live in [`docs/`](./docs/README.md):

- [Design](./docs/design.md) — the problem, approach, architecture.
- [Quickstart](./docs/quickstart.md) — install, server + client, feature list.
- [Streaming](./docs/streaming.md) — WebSocket subscriptions and SSE streams.
- [Authentication](./docs/authentication.md) — bearer tokens, cookie sessions, CSRF.
- [Observability](./docs/observability.md) — observers, timeouts, body limits.
- [Framework integrations](./docs/integrations.md) — FastAPI, Django, Sanic, Litestar.
- [TanStack example](./docs/tanstack.md) — Router + Query end-to-end.
- [Performance](./docs/performance.md) — benchmarks.
- [Project layout](./docs/project-layout.md) — module map.
- [Roadmap](./docs/roadmap.md) — phases, tech stack, status.

## License

MIT — see [LICENSE](./LICENSE).
