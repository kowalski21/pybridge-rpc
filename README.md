# PyBridge

End-to-end type safety from Python to TypeScript — no codegen ceremony, no schema drift.

Define procedures in Python with standard type hints + Pydantic. Run one command. Get a fully typed TypeScript client.

```bash
pip install -e .
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

Phases 1–3 are complete and tested. 33 tests pass.

> Use conda environment `hacks`.
