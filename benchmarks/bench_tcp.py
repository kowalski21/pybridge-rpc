"""TCP / uvicorn benchmark for PyBridge using ApacheBench (`ab`).

Boots uvicorn in a subprocess and drives it over real sockets with `ab`, which
is a proper C load generator (the httpx-based version we tried earlier was
bottlenecked by the client, not the server). `ab` ships with macOS by default
and is available on most Linux distros as `apache2-utils`.

Run:
    python benchmarks/bench_tcp.py
    python benchmarks/bench_tcp.py --requests 20000 --concurrency 100 --workers 2
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path


def free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_ready(host: str, port: int, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                # uvicorn accepts; one more health check via /rpc/health.ping
                import urllib.request, urllib.error
                req = urllib.request.Request(
                    f"http://{host}:{port}/rpc/health.ping", data=b"", method="POST"
                )
                try:
                    urllib.request.urlopen(req, timeout=1.0).read()
                    return
                except urllib.error.URLError:
                    pass
        except OSError:
            pass
        time.sleep(0.1)
    raise RuntimeError(f"uvicorn not ready at {host}:{port}")


_AB_NUM = r"([\d.]+)"
_AB_FIELDS = {
    "rps": re.compile(rf"Requests per second:\s+{_AB_NUM}"),
    "mean_ms": re.compile(rf"Time per request:\s+{_AB_NUM}\s+\[ms\] \(mean\)"),
    "failed": re.compile(rf"Failed requests:\s+(\d+)"),
}


def parse_ab(output: str) -> dict:
    out: dict[str, float] = {}
    for k, rx in _AB_FIELDS.items():
        m = rx.search(output)
        if m:
            out[k] = float(m.group(1))
    return out


def run_ab(
    url: str, concurrency: int, requests: int, body_path: str | None = None
) -> dict:
    cmd = [
        "ab", "-q", "-k",
        "-c", str(concurrency),
        "-n", str(requests),
        "-T", "application/json",
    ]
    if body_path is not None:
        cmd.extend(["-p", body_path])
    else:
        cmd.extend(["-p", "/dev/null"])
    cmd.append(url)
    res = subprocess.run(cmd, capture_output=True, text=True)
    return parse_ab(res.stdout)


def format_row(name: str, parsed: dict) -> str:
    rps = parsed.get("rps", 0.0)
    mean = parsed.get("mean_ms", 0.0)
    failed = int(parsed.get("failed", 0))
    return f"{name:<32} rps={rps:>9.0f}  mean={mean:>6.2f}ms  failed={failed}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--requests", type=int, default=10000)
    ap.add_argument("--concurrency", type=int, default=50)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    if shutil.which("ab") is None:
        sys.exit("error: ApacheBench (`ab`) is not installed. macOS ships it; "
                 "on Debian/Ubuntu run `apt install apache2-utils`.")

    port = free_port()
    print(f"PyBridge TCP benchmark via `ab`  (workers={args.workers}, port={port}, "
          f"requests={args.requests}, concurrency={args.concurrency})")
    print("-" * 90)

    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "examples.basic:app",
            "--host", args.host, "--port", str(port),
            "--workers", str(args.workers),
            "--log-level", "warning", "--no-access-log",
        ],
        cwd=str(Path(__file__).resolve().parents[1]),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        wait_ready(args.host, port)

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"name": "x", "email": "x@x.x"}, f)
            create_body = f.name

        # seed a user via plain urllib so users.get works
        import urllib.request
        req = urllib.request.Request(
            f"http://{args.host}:{port}/rpc/users.create",
            data=json.dumps({"name": "seed", "email": "s@s.s"}).encode(),
            headers={"content-type": "application/json"},
            method="POST",
        )
        seed_id = json.loads(urllib.request.urlopen(req).read())["id"]
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"id": seed_id}, f)
            get_body = f.name

        base = f"http://{args.host}:{port}"
        print(format_row("health.ping (no input)",
                         run_ab(f"{base}/rpc/health.ping", args.concurrency, args.requests)))
        print(format_row("users.get (validated input)",
                         run_ab(f"{base}/rpc/users.get", args.concurrency, args.requests, get_body)))
        print(format_row("users.list (model array out)",
                         run_ab(f"{base}/rpc/users.list", args.concurrency, args.requests)))
        print(format_row("users.create (in+out model)",
                         run_ab(f"{base}/rpc/users.create", args.concurrency, args.requests, create_body)))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    main()
