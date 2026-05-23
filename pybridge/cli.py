from __future__ import annotations

import importlib
import json
import signal
import sys
import threading
from pathlib import Path

import click

from .bridge import Bridge
from .codegen import generate
from .openapi import generate_openapi
from .watcher import HAS_WATCHFILES, watch_paths


@click.group()
def main() -> None:
    """PyBridge CLI."""


@main.command("generate")
@click.option("--bridge", "bridge_ref", required=True, help="module:attribute reference to a Bridge instance.")
@click.option("--out", "out_path", required=True, type=click.Path(path_type=Path, dir_okay=False))
@click.option("--watch", is_flag=True, help="Re-generate on file changes.")
@click.option("--watch-dir", type=click.Path(path_type=Path, file_okay=False, exists=True), default=None, help="Directory to watch (defaults to cwd).")
@click.option("--hooks", is_flag=True, help="Emit React Query hook helpers.")
def generate_cmd(bridge_ref: str, out_path: Path, watch: bool, watch_dir: Path | None, hooks: bool) -> None:
    """Generate the TypeScript client."""
    _emit(bridge_ref, out_path, hooks)
    if not watch:
        return
    root = (watch_dir or Path.cwd()).resolve()
    backend = "watchfiles" if HAS_WATCHFILES else "polling"
    click.echo(f"watching {root} via {backend} (Ctrl+C to stop)")

    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())

    def on_change(paths: list[Path]) -> None:
        click.echo(f"changed: {', '.join(_short(p, root) for p in paths[:3])}{'...' if len(paths) > 3 else ''}")
        _reload_and_emit(bridge_ref, out_path, hooks)

    watch_paths(root, on_change, stop)
    click.echo("stopped.")


@main.command("openapi")
@click.option("--bridge", "bridge_ref", required=True)
@click.option("--out", "out_path", required=True, type=click.Path(path_type=Path, dir_okay=False))
@click.option("--title", default="PyBridge API")
@click.option("--version", default="0.1.0")
def openapi_cmd(bridge_ref: str, out_path: Path, title: str, version: str) -> None:
    """Export an OpenAPI 3.0 spec."""
    bridge = _load_bridge(bridge_ref)
    spec = generate_openapi(bridge, title=title, version=version)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(spec, indent=2))
    click.echo(f"wrote {out_path}")


def _emit(bridge_ref: str, out_path: Path, hooks: bool) -> None:
    bridge = _load_bridge(bridge_ref)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(generate(bridge, with_hooks=hooks))
    click.echo(f"wrote {out_path} ({len(bridge.procedures)} procedures)")


def _reload_and_emit(bridge_ref: str, out_path: Path, hooks: bool) -> None:
    module_name = bridge_ref.split(":", 1)[0]
    for name in list(sys.modules):
        if name == module_name or name.startswith(module_name + "."):
            del sys.modules[name]
    try:
        _emit(bridge_ref, out_path, hooks)
    except Exception as e:
        click.echo(f"error: {e}", err=True)


def _short(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _load_bridge(ref: str) -> Bridge:
    if ":" not in ref:
        raise click.ClickException(f"--bridge must be 'module:attr', got {ref!r}")
    module_name, attr = ref.split(":", 1)
    if str(Path.cwd()) not in sys.path:
        sys.path.insert(0, str(Path.cwd()))
    module = importlib.import_module(module_name)
    obj = getattr(module, attr)
    if not isinstance(obj, Bridge):
        raise click.ClickException(f"{ref} is not a Bridge instance")
    return obj


if __name__ == "__main__":
    main()
