# Observability

Drop in an observer to wire OpenTelemetry, Sentry, structlog, or anything else. All hooks are optional; errors raised inside an observer are swallowed and never affect the request.

```python
@bridge.observer
class LogObserver:
    async def on_request_start(self, ev): log.info("rpc.start", path=ev.path)
    async def on_request_end(self, ev):   log.info("rpc.end", path=ev.path, ms=ev.duration_ms)
    async def on_error(self, ev):         log.warning("rpc.err", path=ev.path, code=ev.code)
```

## Limits

Declare `timeout=` (seconds) and `max_body=` (bytes) per procedure. They map to HTTP 504 and 413 with stable error codes (`TIMEOUT`, `PAYLOAD_TOO_LARGE`):

```python
@bridge.procedure("reports.heavy", timeout=30, max_body=1_000_000)
async def heavy(input: ReportInput) -> Report: ...
```
