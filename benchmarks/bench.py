"""In-process ASGI benchmark for PyBridge.

Measures framework overhead without TCP/kernel noise by driving the ASGI app
directly via httpx.AsyncClient(ASGITransport).

Run:
    python benchmarks/bench.py
    python benchmarks/bench.py --requests 20000 --concurrency 100
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from examples.basic import bridge, app  # noqa: E402
from pybridge.codegen import generate  # noqa: E402
from pybridge.openapi import generate_openapi  # noqa: E402


def percentile(samples: list[float], p: float) -> float:
    if not samples:
        return 0.0
    s = sorted(samples)
    k = max(0, min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1)))))
    return s[k]


def format_row(name: str, total_s: float, n: int, lat_us: list[float]) -> str:
    rps = n / total_s if total_s > 0 else 0.0
    mean = statistics.fmean(lat_us)
    p50 = percentile(lat_us, 50)
    p95 = percentile(lat_us, 95)
    p99 = percentile(lat_us, 99)
    return (
        f"{name:<32} "
        f"n={n:>6}  "
        f"rps={rps:>8.0f}  "
        f"mean={mean:>7.1f}us  "
        f"p50={p50:>7.1f}us  "
        f"p95={p95:>7.1f}us  "
        f"p99={p99:>7.1f}us"
    )


async def run_scenario(
    name: str,
    client: httpx.AsyncClient,
    path: str,
    payload,
    requests: int,
    concurrency: int,
) -> str:
    sem = asyncio.Semaphore(concurrency)
    latencies: list[float] = [0.0] * requests
    url = f"/rpc/{path}"

    async def one(i: int) -> None:
        async with sem:
            t0 = time.perf_counter()
            if payload is None:
                r = await client.post(url)
            else:
                r = await client.post(url, json=payload)
            latencies[i] = (time.perf_counter() - t0) * 1_000_000
            if r.status_code >= 400:
                raise RuntimeError(f"{path} -> {r.status_code} {r.text[:120]}")

    # warmup
    for _ in range(min(50, requests)):
        if payload is None:
            await client.post(url)
        else:
            await client.post(url, json=payload)

    t0 = time.perf_counter()
    await asyncio.gather(*(one(i) for i in range(requests)))
    elapsed = time.perf_counter() - t0
    return format_row(name, elapsed, requests, latencies)


async def run_batch_scenario(
    name: str,
    client: httpx.AsyncClient,
    calls: list[dict],
    requests: int,
    concurrency: int,
) -> str:
    sem = asyncio.Semaphore(concurrency)
    latencies: list[float] = [0.0] * requests

    async def one(i: int) -> None:
        async with sem:
            t0 = time.perf_counter()
            r = await client.post("/rpc/_batch", json=calls)
            latencies[i] = (time.perf_counter() - t0) * 1_000_000
            if r.status_code >= 400:
                raise RuntimeError(f"_batch -> {r.status_code} {r.text[:120]}")

    for _ in range(min(20, requests)):
        await client.post("/rpc/_batch", json=calls)

    t0 = time.perf_counter()
    await asyncio.gather(*(one(i) for i in range(requests)))
    elapsed = time.perf_counter() - t0
    # report per-batch latency AND per-inner-call throughput
    rps_batches = requests / elapsed if elapsed else 0
    rps_calls = (requests * len(calls)) / elapsed if elapsed else 0
    mean = statistics.fmean(latencies)
    p50 = percentile(latencies, 50)
    p95 = percentile(latencies, 95)
    p99 = percentile(latencies, 99)
    return (
        f"{name:<32} "
        f"n={requests:>6}  "
        f"rps={rps_batches:>8.0f}  "
        f"mean={mean:>7.1f}us  "
        f"p50={p50:>7.1f}us  "
        f"p95={p95:>7.1f}us  "
        f"p99={p99:>7.1f}us  "
        f"  ({len(calls)} calls/batch -> {rps_calls:.0f} inner-calls/s)"
    )


def bench_codegen(iters: int = 200) -> None:
    print()
    print("== Introspection / codegen (one-shot cost) ==")
    samples = []
    for _ in range(iters):
        t0 = time.perf_counter()
        generate(bridge)
        samples.append((time.perf_counter() - t0) * 1000)
    mean = statistics.fmean(samples)
    print(f"  generate(bridge)        x{iters}  mean={mean:6.3f}ms  p95={percentile(samples,95):6.3f}ms")

    samples = []
    for _ in range(iters):
        t0 = time.perf_counter()
        generate_openapi(bridge)
        samples.append((time.perf_counter() - t0) * 1000)
    mean = statistics.fmean(samples)
    print(f"  generate_openapi(bridge) x{iters}  mean={mean:6.3f}ms  p95={percentile(samples,95):6.3f}ms")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--requests", type=int, default=10000)
    ap.add_argument("--concurrency", type=int, default=50)
    args = ap.parse_args()

    print(f"PyBridge in-process benchmark  (requests={args.requests}, concurrency={args.concurrency})")
    print("-" * 100)

    # seed one user so users.get / users.list have something
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        seeded = await client.post("/rpc/users.create", json={"name": "seed", "email": "s@s.s"})
        seed_id = seeded.json()["id"]

        print("== Per-procedure (HTTP /rpc/*) ==")
        print(await run_scenario("health.ping (no input)", client, "health.ping", None, args.requests, args.concurrency))
        print(await run_scenario("users.get (validated input)", client, "users.get", {"id": seed_id}, args.requests, args.concurrency))
        print(await run_scenario("users.list (model array out)", client, "users.list", None, args.requests, args.concurrency))
        print(await run_scenario("users.create (in+out model)", client, "users.create", {"name": "x", "email": "x@x.x"}, args.requests // 4, args.concurrency))

        print()
        print("== Batch endpoint ==")
        small_batch = [{"path": "health.ping"} for _ in range(10)]
        big_batch = [{"path": "health.ping"} for _ in range(50)]
        print(await run_batch_scenario("batch x10 health.ping", client, small_batch, args.requests // 10, args.concurrency))
        print(await run_batch_scenario("batch x50 health.ping", client, big_batch, args.requests // 50, args.concurrency))

    bench_codegen()


if __name__ == "__main__":
    asyncio.run(main())
