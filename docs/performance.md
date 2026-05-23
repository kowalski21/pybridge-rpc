# Performance

In-process ASGI benchmark (`benchmarks/bench.py`, in-process, latency-focused):

| Scenario | p50 | p95 |
|---|---:|---:|
| `health.ping` (no input) | 99 µs | 113 µs |
| `users.get` (Pydantic-validated input) | 114 µs | 133 µs |
| `users.create` (in + out model) | 118 µs | 142 µs |

Through real TCP (`benchmarks/bench_tcp.py`, uvicorn + ApacheBench):

| Scenario | RPS (1 worker) | RPS (2 workers) |
|---|---:|---:|
| `health.ping` | ~19k | ~40k |
| `users.create` | ~13k | ~24k |

PyBridge adds ~20–30 µs of Pydantic-validate + dump overhead on top of Starlette's per-request cost; codegen takes sub-millisecond on typical schemas, so `--watch` feels instant.
