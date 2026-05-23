from __future__ import annotations

import inspect
import json
import typing as t

from pydantic import BaseModel, TypeAdapter, ValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

import asyncio
import time

from .bridge import Bridge, Procedure
from .context import Context
from .errors import ProcedureError
from .observability import RequestEvent
from .uploads import UploadFile, model_has_upload


def build_asgi(bridge: Bridge, middleware: list | None = None) -> Starlette:
    routes: list = []
    has_subscription = False
    for proc in bridge.procedures.values():
        if proc.kind == "subscription":
            has_subscription = True
            continue
        if proc.kind == "stream":
            routes.append(
                Route(f"/rpc/{proc.path}", _make_stream_endpoint(bridge, proc), methods=["POST"])
            )
            continue
        routes.append(
            Route(f"/rpc/{proc.path}", _make_endpoint(bridge, proc), methods=["POST"])
        )
    routes.append(Route("/rpc/_batch", _make_batch_endpoint(bridge), methods=["POST"]))
    if has_subscription:
        routes.append(WebSocketRoute("/ws", _make_ws_endpoint(bridge)))
    return Starlette(routes=routes, middleware=list(middleware or []))


def _make_endpoint(bridge: Bridge, proc: Procedure):
    input_adapter = TypeAdapter(proc.input_type) if proc.input_type else None
    output_adapter = TypeAdapter(proc.output_type) if proc.output_type else None
    multipart = proc.input_type is not None and model_has_upload(proc.input_type)

    async def endpoint(request: Request) -> JSONResponse:
        ctx = Context(
            path=proc.path,
            headers={k.decode(): v.decode() for k, v in request.headers.raw},
            request=request,
        )
        ev = RequestEvent(path=proc.path, kind=proc.kind, headers=ctx.headers, state=ctx.state)
        await _emit(bridge, "on_request_start", ev)
        t0 = time.perf_counter()
        try:
            if proc.max_body is not None:
                size = _content_length(request)
                if size is not None and size > proc.max_body:
                    raise ProcedureError(code="PAYLOAD_TOO_LARGE", message=f"body exceeds {proc.max_body} bytes")
            payload = await _read_payload(request, multipart)
            result = await _invoke(bridge, proc, ctx, payload, input_adapter, output_adapter)
            ev.duration_ms = (time.perf_counter() - t0) * 1000
            await _emit(bridge, "on_request_end", ev)
            return JSONResponse(result)
        except ProcedureError as e:
            ev.duration_ms = (time.perf_counter() - t0) * 1000
            ev.code = e.code
            ev.exception = e
            await _emit(bridge, "on_error", ev)
            status = 413 if e.code == "PAYLOAD_TOO_LARGE" else (504 if e.code == "TIMEOUT" else 400)
            return JSONResponse({"error": e.to_dict()}, status_code=status)
        except ValidationError as e:
            ev.duration_ms = (time.perf_counter() - t0) * 1000
            ev.code = "INVALID_INPUT"
            ev.exception = e
            await _emit(bridge, "on_error", ev)
            return JSONResponse(
                {"error": {"code": "INVALID_INPUT", "message": str(e), "data": e.errors()}},
                status_code=422,
            )

    return endpoint


def _content_length(request: Request) -> int | None:
    cl = request.headers.get("content-length")
    if cl is None:
        return None
    try:
        return int(cl)
    except ValueError:
        return None


async def _emit(bridge: Bridge, hook: str, ev: RequestEvent) -> None:
    for obs in bridge.observers:
        fn = getattr(obs, hook, None)
        if fn is None:
            continue
        try:
            await fn(ev)
        except Exception:
            pass  # observers must never break the request


def _make_stream_endpoint(bridge: Bridge, proc: Procedure):
    input_adapter = TypeAdapter(proc.input_type) if proc.input_type else None
    output_adapter = TypeAdapter(proc.output_type) if proc.output_type else None

    async def endpoint(request: Request) -> StreamingResponse:
        ctx = Context(
            path=proc.path,
            headers={k.decode(): v.decode() for k, v in request.headers.raw},
            request=request,
        )
        payload = await _read_payload(request, multipart=False)

        async def body():
            try:
                kwargs = _build_kwargs(proc, payload, input_adapter, ctx)
            except ValidationError as e:
                yield _sse_event("error", {"code": "INVALID_INPUT", "message": str(e), "data": e.errors()})
                return

            async def call() -> t.AsyncIterator:
                return proc.handler(**kwargs)

            runner = _wrap_middlewares(bridge, proc, ctx, call)
            try:
                agen = await runner()
            except ProcedureError as e:
                yield _sse_event("error", e.to_dict())
                return

            try:
                async for item in agen:
                    if await request.is_disconnected():
                        break
                    yield _sse_event("next", _dump(item, output_adapter))
                yield _sse_event("complete", None)
            except ProcedureError as e:
                yield _sse_event("error", e.to_dict())
            finally:
                aclose = getattr(agen, "aclose", None)
                if aclose:
                    await aclose()

        return StreamingResponse(
            body(),
            media_type="text/event-stream",
            headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
        )

    return endpoint


def _sse_event(event: str, data: t.Any) -> bytes:
    payload = "" if data is None else json.dumps(data, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n".encode()


def _make_batch_endpoint(bridge: Bridge):
    async def endpoint(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return JSONResponse(
                {"error": {"code": "INVALID_INPUT", "message": "batch body must be JSON"}},
                status_code=400,
            )
        if not isinstance(body, list):
            return JSONResponse(
                {"error": {"code": "INVALID_INPUT", "message": "batch body must be a list"}},
                status_code=400,
            )

        headers = {k.decode(): v.decode() for k, v in request.headers.raw}
        results: list[dict] = []
        for entry in body:
            path = entry.get("path") if isinstance(entry, dict) else None
            input_data = entry.get("input") if isinstance(entry, dict) else None
            proc = bridge.procedures.get(path or "")
            if proc is None or proc.kind == "subscription":
                results.append({"error": {"code": "NOT_FOUND", "message": f"unknown procedure {path!r}"}})
                continue
            ctx = Context(path=proc.path, headers=dict(headers), request=request)
            input_adapter = TypeAdapter(proc.input_type) if proc.input_type else None
            output_adapter = TypeAdapter(proc.output_type) if proc.output_type else None
            try:
                value = await _invoke(bridge, proc, ctx, input_data, input_adapter, output_adapter)
                results.append({"result": value})
            except ProcedureError as e:
                results.append({"error": e.to_dict()})
            except ValidationError as e:
                results.append(
                    {"error": {"code": "INVALID_INPUT", "message": str(e), "data": e.errors()}}
                )
        return JSONResponse(results)

    return endpoint


def _make_ws_endpoint(bridge: Bridge):
    async def endpoint(ws: WebSocket) -> None:
        conn_ctx = Context(
            path="<ws>",
            headers={k.decode(): v.decode() for k, v in ws.headers.raw},
            request=ws,
        )
        ev = RequestEvent(path="<ws>", kind="connect", headers=conn_ctx.headers, state=conn_ctx.state)
        await _emit(bridge, "on_request_start", ev)
        t0 = time.perf_counter()

        # Run connect handlers BEFORE accepting; if any rejects, close with 1008.
        try:
            for handler in bridge.connect_handlers:
                await handler(conn_ctx)
        except ProcedureError as e:
            await ws.close(code=1008, reason=e.message[:120])
            ev.code = e.code
            ev.exception = e
            ev.duration_ms = (time.perf_counter() - t0) * 1000
            await _emit(bridge, "on_error", ev)
            return

        await ws.accept()
        try:
            while True:
                msg = await ws.receive_json()
                kind = msg.get("type")
                sub_id = msg.get("id")
                if kind != "subscribe":
                    await ws.send_json({"id": sub_id, "type": "error", "error": {"code": "INVALID_INPUT", "message": "expected type=subscribe"}})
                    continue
                path = msg.get("path")
                proc = bridge.procedures.get(path or "")
                if proc is None or proc.kind != "subscription":
                    await ws.send_json({"id": sub_id, "type": "error", "error": {"code": "NOT_FOUND", "message": f"no subscription {path!r}"}})
                    continue

                sub_ev = RequestEvent(
                    path=proc.path, kind="subscription",
                    headers=conn_ctx.headers, state=dict(conn_ctx.state),
                )
                await _emit(bridge, "on_request_start", sub_ev)
                sub_t0 = time.perf_counter()
                try:
                    await _run_subscription(bridge, proc, ws, sub_id, msg.get("input"), conn_ctx)
                    sub_ev.duration_ms = (time.perf_counter() - sub_t0) * 1000
                    await _emit(bridge, "on_request_end", sub_ev)
                except ProcedureError as e:
                    sub_ev.duration_ms = (time.perf_counter() - sub_t0) * 1000
                    sub_ev.code = e.code
                    sub_ev.exception = e
                    await _emit(bridge, "on_error", sub_ev)
                    await ws.send_json({"id": sub_id, "type": "error", "error": e.to_dict()})
        except WebSocketDisconnect:
            ev.duration_ms = (time.perf_counter() - t0) * 1000
            await _emit(bridge, "on_request_end", ev)
            return

    return endpoint


async def _run_subscription(
    bridge: Bridge, proc: Procedure, ws: WebSocket, sub_id, raw_input,
    conn_ctx: Context | None = None,
) -> None:
    ctx = Context(
        path=proc.path,
        headers=dict(conn_ctx.headers) if conn_ctx else {k.decode(): v.decode() for k, v in ws.headers.raw},
        request=ws,
    )
    if conn_ctx is not None:
        ctx.state.update(conn_ctx.state)  # inherit per-connection auth/etc
    input_adapter = TypeAdapter(proc.input_type) if proc.input_type else None
    output_adapter = TypeAdapter(proc.output_type) if proc.output_type else None

    async def call() -> t.AsyncIterator:
        kwargs = _build_kwargs(proc, raw_input, input_adapter, ctx)
        return proc.handler(**kwargs)

    runner = _wrap_middlewares(bridge, proc, ctx, call)
    agen = await runner()
    try:
        async for item in agen:
            await ws.send_json({"id": sub_id, "type": "next", "value": _dump(item, output_adapter)})
        await ws.send_json({"id": sub_id, "type": "complete"})
    finally:
        aclose = getattr(agen, "aclose", None)
        if aclose:
            await aclose()


async def _invoke(
    bridge: Bridge,
    proc: Procedure,
    ctx: Context,
    payload: t.Any,
    input_adapter: TypeAdapter | None,
    output_adapter: TypeAdapter | None,
) -> t.Any:
    async def call() -> t.Any:
        kwargs = _build_kwargs(proc, payload, input_adapter, ctx)
        result = proc.handler(**kwargs)
        if inspect.isawaitable(result):
            result = await result
        return _dump(result, output_adapter)

    runner = _wrap_middlewares(bridge, proc, ctx, call)
    if proc.timeout is not None:
        try:
            return await asyncio.wait_for(runner(), proc.timeout)
        except asyncio.TimeoutError:
            raise ProcedureError(code="TIMEOUT", message=f"exceeded {proc.timeout}s")
    return await runner()


def _wrap_middlewares(
    bridge: Bridge, proc: Procedure, ctx: Context, terminal: t.Callable[[], t.Awaitable[t.Any]]
) -> t.Callable[[], t.Awaitable[t.Any]]:
    chain = list(bridge.global_middlewares) + list(proc.middlewares)
    runner: t.Callable[[], t.Awaitable[t.Any]] = terminal
    for mw in reversed(chain):
        runner = _bind_middleware(mw, ctx, runner)
    return runner


def _bind_middleware(mw, ctx: Context, next_call: t.Callable[[], t.Awaitable[t.Any]]):
    async def run() -> t.Any:
        async def next_(passed_ctx: Context | None = None) -> t.Any:
            return await next_call()
        return await mw(ctx, next_)
    return run


async def _read_payload(request: Request, multipart: bool) -> t.Any:
    if multipart:
        form = await request.form()
        data: dict[str, t.Any] = {}
        meta_raw = form.get("__json__")
        if isinstance(meta_raw, str):
            data.update(json.loads(meta_raw))
        for key in form:
            if key == "__json__":
                continue
            values = form.getlist(key)
            files = [v for v in values if hasattr(v, "filename")]
            if files:
                uploaded = [
                    UploadFile(filename=v.filename or "", content_type=v.content_type or "application/octet-stream", data=await v.read())
                    for v in files
                ]
                data[key] = uploaded if len(uploaded) > 1 else uploaded[0]
            else:
                data[key] = values[0] if len(values) == 1 else values
        return data
    body = await request.body()
    if not body:
        return None
    return json.loads(body)


def _build_kwargs(
    proc: Procedure, payload: t.Any, input_adapter: TypeAdapter | None, ctx: Context
) -> dict[str, t.Any]:
    kwargs: dict[str, t.Any] = {}
    if proc.wants_ctx:
        kwargs["ctx"] = ctx
    if input_adapter is None:
        return kwargs
    validated = input_adapter.validate_python(payload, strict=False)
    sig = inspect.signature(proc.handler)
    for name in sig.parameters:
        if name == "ctx":
            continue
        kwargs[name] = validated
        break
    return kwargs


def _dump(value: t.Any, adapter: TypeAdapter | None) -> t.Any:
    if adapter is not None:
        try:
            return adapter.dump_python(value, mode="json")
        except Exception:
            pass
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return value
