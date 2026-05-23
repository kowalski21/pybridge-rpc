# Streaming

PyBridge has two streaming primitives, picked by transport:

| Decorator | Transport | TS shape | Use for |
|---|---|---|---|
| `@bridge.subscription("ticks.stream")` | WebSocket | `Subscription<T>` (async iterator) | long-lived pushes, server fan-out, bidirectional setup |
| `@bridge.stream("chat.complete")` | HTTP / SSE | `Stream<T>` (async iterator + `cancel()`) | one-shot streamed responses (LLM tokens, progress events) |

```python
@bridge.stream("chat.complete")
async def chat_complete(input: ChatInput) -> AsyncIterator[str]:
    for token in await llm.stream(input.prompt):
        yield token
```

```ts
const s = api.chat.complete.stream({ prompt: "hello" });
for await (const tok of s) process.stdout.write(tok);
// or: s.cancel();
```

Both yield typed values; both surface Python-raised `ProcedureError` as a typed JS error.

**WebSocket auth.** Register a connect-time handler so auth runs *once per connection*, not per subscribe message:

```python
@bridge.on_connect
async def authenticate(ctx: Context):
    user = await verify_token(ctx.headers.get("authorization", ""))
    if not user:
        raise ProcedureError(code="UNAUTHORIZED", message="bad token")
    ctx.user = user  # inherited by every subscription on this socket
```

Raising `ProcedureError` rejects the upgrade with WS close code 1008 (policy violation), so misbehaving clients never reach any subscription handler. The handler's `ctx.state` is copied into each subscription's context, so handlers can read `ctx.user` without re-running auth.
