# Framework integrations

PyBridge is a plain ASGI app, so anything that speaks ASGI can host it. The package ships two opinionated integrations and one general-purpose pattern.

## FastAPI

```python
from fastapi import FastAPI
from pybridge.integrations import mount_fastapi

app = FastAPI(title="My App")

@app.get("/api/version")
async def version(): return {"v": "1.0"}

mount_fastapi(app, bridge, prefix="/api")
```

What you get:

- **Both stacks coexist.** FastAPI routes and PyBridge `/rpc/*` live under the same uvicorn process; `app.mount()` does the dispatch.
- **One unified `/docs` and `/redoc`.** PyBridge procedures are merged into FastAPI's OpenAPI spec on demand, so they render alongside your FastAPI routes in Swagger UI with full request/response schemas. "Try it out" hits the real endpoints. (`include_in_schema=False` to opt out.)
- **WebSocket subscriptions and SSE streams** travel through the mount unchanged.
- **APIRouter compatibility.** Side-by-side with `app.include_router(...)`, same-prefix with `app.include_router(prefix="/internal")` + `mount_fastapi(app, bridge, prefix="/internal")` — both verified in tests.

See [`examples/fastapi_mount.py`](../examples/fastapi_mount.py).

## Django (+ django-ninja, optional)

PyBridge plugs in at the **ASGI router** level, not Django's URLconf — Django's `path(...)` is HTTP-only, and PyBridge needs WebSocket and SSE.

```python
# asgi.py
import django
from django.conf import settings
# ... settings.configure(...) / DJANGO_SETTINGS_MODULE ...
django.setup()

from django.core.asgi import get_asgi_application
from myapp.bridge import bridge

django_app = get_asgi_application()
bridge_app = bridge.asgi()

async def application(scope, receive, send):
    if scope["type"] in {"http", "websocket"}:
        path = scope.get("path", "")
        if path.startswith("/rpc") or path == "/ws":
            await bridge_app(scope, receive, send)
            return
    await django_app(scope, receive, send)
```

```bash
uvicorn myapp.asgi:application
```

Now `/rpc/*` and `/ws` are served by PyBridge; everything else (Django admin, ORM-backed views, static files, **django-ninja**, DRF) keeps working unchanged.

**Why combine PyBridge with django-ninja?**

| | django-ninja | PyBridge |
|---|---|---|
| Style | REST endpoints, FastAPI-like decorators | Typed RPC procedures |
| Pydantic schemas | ✅ | ✅ (shared models work in both) |
| Generated TS client | ❌ | ✅ |
| WebSocket / SSE | ❌ | ✅ |
| Django admin / ORM | ✅ (native) | via Django process |
| OpenAPI / Swagger | ✅ at `/api/docs` | ✅ via `pybridge openapi` |

You get Django's ecosystem (admin, ORM, sessions, auth backends, migrations) plus django-ninja for any REST surface you need to expose to non-TS clients, plus PyBridge for the typed RPC layer your TypeScript app actually consumes. The Pydantic models are shared across all three.

A note on order: **configure Django settings before importing django-ninja** — ninja reads settings at module import time and will fail with `ImproperlyConfigured` if Django isn't ready yet.

Full runnable example at [`examples/django_ninja.py`](../examples/django_ninja.py) — Django view + `NinjaAPI` + PyBridge procedures + WebSocket subscription + SSE stream, all on one uvicorn process.

## Sanic

Sanic is its own framework — it doesn't support mounting external ASGI apps inside it. The integration is the same composition pattern as Django, packaged behind an `asgi_dispatch` helper:

```python
from sanic import Sanic
from sanic.response import json as sanic_json

from pybridge.integrations import asgi_dispatch
from myapp.bridge import bridge

sanic_app = Sanic("MyApp")

@sanic_app.get("/")
async def home(request):
    return sanic_json({"app": "sanic"})

application = asgi_dispatch(
    ("/rpc", bridge.asgi()),
    ("/ws", bridge.asgi()),
    default=sanic_app,
)
```

```bash
uvicorn myapp.asgi:application
```

`asgi_dispatch` matches paths in order — the first prefix to match wins — and forwards anything else to `default`. It's the same helper to reach for whenever you need to compose two ASGI frameworks side by side (Sanic, Quart, Litestar, plain Starlette, your own dispatcher).

Full runnable example at [`examples/sanic_mount.py`](../examples/sanic_mount.py).

## Litestar

Litestar supports mounting ASGI apps natively via `@asgi(path, is_mount=True)`, but it strips the mount prefix before delegating — and PyBridge's internal routes are defined under `/rpc/*`. The cleanest composition is the same `asgi_dispatch` pattern used for Sanic:

```python
from litestar import Litestar, get
from pybridge.integrations import asgi_dispatch
from myapp.bridge import bridge

@get("/")
async def home() -> dict:
    return {"app": "litestar"}

litestar_app = Litestar(route_handlers=[home])

application = asgi_dispatch(
    ("/rpc", bridge.asgi()),
    ("/ws", bridge.asgi()),
    default=litestar_app,
)
```

```bash
uvicorn myapp.asgi:application
```

Litestar's own OpenAPI schema at `/schema/openapi.json` keeps working — PyBridge exposes its spec separately via `pybridge openapi`. Full example at [`examples/litestar_mount.py`](../examples/litestar_mount.py).

## Anything else (Starlette, Quart, Hypercorn, …)

If your framework speaks ASGI, the same pattern works: build `bridge.asgi()`, then either mount it under the host app (Starlette/FastAPI) or compose with `asgi_dispatch(...)` at the entry point.
