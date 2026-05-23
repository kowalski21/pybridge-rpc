"""Framework integration helpers."""

from __future__ import annotations

import typing as t

from .bridge import Bridge


def mount_fastapi(
    app,
    bridge: Bridge,
    *,
    prefix: str = "",
    include_in_schema: bool = True,
) -> None:
    """Mount a PyBridge ASGI app into a FastAPI / Starlette app.

    ``prefix`` is stripped before delegating; the procedures are still exposed
    at ``/rpc/...`` under the chosen prefix.

    When ``include_in_schema=True`` (default) and ``app`` is a FastAPI
    instance, the bridge's procedures are merged into FastAPI's OpenAPI spec
    so they appear in ``/docs`` and ``/redoc`` alongside the app's own routes.
    Pass ``include_in_schema=False`` to skip the merge (e.g. for plain
    Starlette apps, or to keep PyBridge undocumented in Swagger UI).
    """
    app.mount(prefix or "/", bridge.asgi())
    if include_in_schema and _is_fastapi(app):
        _patch_fastapi_openapi(app, bridge, prefix)


def _is_fastapi(app) -> bool:
    return type(app).__module__.startswith("fastapi.")


def _patch_fastapi_openapi(app, bridge: Bridge, prefix: str) -> None:
    """Wrap ``app.openapi`` so PyBridge paths + schemas are merged in."""
    from .openapi import generate_openapi

    original = app.openapi
    normalized_prefix = prefix.rstrip("/") if prefix else ""

    def patched_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        schema = original()
        bridge_spec = generate_openapi(
            bridge,
            title=app.title or "PyBridge API",
            version=app.version or "0.1.0",
        )

        paths = schema.setdefault("paths", {})
        for path, item in bridge_spec.get("paths", {}).items():
            paths[f"{normalized_prefix}{path}"] = item

        merged_schemas = (
            schema.setdefault("components", {}).setdefault("schemas", {})
        )
        for name, defn in bridge_spec.get("components", {}).get("schemas", {}).items():
            merged_schemas.setdefault(name, defn)

        app.openapi_schema = schema
        return schema

    app.openapi = patched_openapi


def asgi_dispatch(*routes, default) -> t.Callable:
    """Compose multiple ASGI apps by path prefix.

    Useful for hosting PyBridge alongside any other ASGI framework whose
    integration model is "run side by side", not "mount inside".

    Example — Sanic + PyBridge::

        from sanic import Sanic
        from pybridge.integrations import asgi_dispatch
        from myapp.bridge import bridge

        sanic_app = Sanic("MyApp")
        bridge_app = bridge.asgi()

        application = asgi_dispatch(
            ("/rpc", bridge_app),
            ("/ws", bridge_app),
            default=sanic_app,
        )

    Routes are matched in order; the first prefix to match wins. ``default``
    handles everything that didn't match (typically your host framework).
    """
    matchers = [(prefix.rstrip("/"), app) for prefix, app in routes]

    async def dispatch(scope, receive, send):
        if scope["type"] in {"http", "websocket"}:
            path = scope.get("path", "")
            for prefix, app in matchers:
                if path == prefix or path.startswith(prefix + "/"):
                    await app(scope, receive, send)
                    return
        await default(scope, receive, send)

    return dispatch


def django_view(bridge: Bridge):
    """Return a Django view callable that delegates to the PyBridge ASGI app.

    Requires Django's ``ASGIRequest`` support (async views). Use as::

        from django.urls import path
        from pybridge.integrations import django_view

        urlpatterns = [path("", django_view(bridge))]
    """
    from asgiref.sync import async_to_sync  # type: ignore

    asgi = bridge.asgi()

    async def _view(scope, receive, send):
        await asgi(scope, receive, send)

    def view(request):  # pragma: no cover - exercised in Django test env
        return async_to_sync(_view)(request.scope, request._receive, request._send)

    return view
