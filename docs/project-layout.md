# Project layout

```
pybridge/
  bridge.py         # Bridge, Group, @procedure / @subscription / @stream
  transport.py     # Starlette ASGI app: HTTP + WebSocket + SSE
  introspect.py    # Python type → TypeScript renderer
  codegen.py        # AppRouter + Proxy client + hooks runtime
  openapi.py        # OpenAPI 3.x exporter
  security.py       # cors(...), csrf(...) middleware helpers
  observability.py # Observer protocol + RequestEvent
  integrations.py  # mount_fastapi(...), asgi_dispatch(...), django_view(...)
  uploads.py        # UploadFile + multipart handling
  cli.py            # `pybridge generate` / `pybridge openapi`

examples/
  basic.py                  # canonical bridge: procedures, subscription, stream, upload
  fastapi_mount.py          # FastAPI + PyBridge in one app
  django_ninja.py           # Django + django-ninja + PyBridge
  sanic_mount.py            # Sanic + PyBridge via asgi_dispatch
  litestar_mount.py         # Litestar + PyBridge via asgi_dispatch
  cookie_auth.py            # cookie-session + CSRF
  tanstack/app.tsx          # TanStack Router + Query usage
  ...

tests/                      # 33 tests covering all of the above
benchmarks/                 # in-process + TCP benchmarks
```
