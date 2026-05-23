# Roadmap

## Phase 1 — Core
- Decorator-based procedure registration with dot-path routing
- Type introspection engine (Python annotations → TypeScript types)
- CLI codegen command (`pybridge generate`)
- Proxy-based TypeScript client runtime
- ASGI transport layer (Starlette)
- Input validation via Pydantic

## Phase 2 — DX
- Watch mode (`pybridge generate --watch`) for auto-regen on save
- Middleware system (auth, logging, rate limiting)
- Typed error propagation
- Batch requests (multiple procedure calls in one HTTP round-trip)
- File upload support

## Phase 3 — Ecosystem
- OpenAPI spec export (for non-TypeScript consumers)
- WebSocket subscriptions for real-time procedures
- Framework integrations (FastAPI mount, Django adapter)
- React Query / TanStack Query hooks generation
- Plugin system for custom type mappings

---

## Tech Stack

**Python**: Pydantic v2, Starlette (ASGI), `inspect` + `typing` + `get_type_hints` for introspection

**TypeScript**: Proxy-based client, zero dependencies beyond `fetch`

**CLI**: Click or Typer for the `pybridge` command

---

## Status

Phases 1–3 are complete and tested. The v0.2 additions (per-procedure limits, observability hooks, docstring → JSDoc, generic `PyBridgeError<Code>`) are in. 33 tests pass.
