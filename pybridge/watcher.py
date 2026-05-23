"""File watcher for `pybridge generate --watch`.

Uses `watchfiles` (Rust-backed, OS events) when available, falls back to
mtime polling. Filtering, debouncing, and overall shape borrowed from
uvicorn's reloader (see uvicorn/supervisors/{watchfilesreload,statreload}.py).
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from pathlib import Path

try:
    from watchfiles import watch as _watchfiles_watch

    HAS_WATCHFILES = True
except ImportError:
    HAS_WATCHFILES = False


DEFAULT_INCLUDES = ("*.py",)
DEFAULT_EXCLUDES = (".*", "*.py[cod]", "*.sw.*", "~*", "__pycache__")


class FileFilter:
    """Glob include/exclude filter. Same defaults as uvicorn."""

    def __init__(
        self,
        includes: tuple[str, ...] = DEFAULT_INCLUDES,
        excludes: tuple[str, ...] = DEFAULT_EXCLUDES,
    ) -> None:
        self.includes = includes
        self.excludes = excludes

    def __call__(self, path: Path) -> bool:
        if not any(path.match(pat) for pat in self.includes):
            return False
        if any(part.startswith(".") or part == "__pycache__" for part in path.parts):
            return False
        return not any(path.match(pat) for pat in self.excludes)


def watch_paths(
    root: Path,
    on_change: Callable[[list[Path]], None],
    stop: threading.Event,
    file_filter: FileFilter | None = None,
    poll_interval: float = 0.4,
) -> None:
    """Block until `stop` is set, calling `on_change(changed_files)` on changes."""
    file_filter = file_filter or FileFilter()
    if HAS_WATCHFILES:
        _watch_with_watchfiles(root, on_change, stop, file_filter)
    else:
        _watch_with_polling(root, on_change, stop, file_filter, poll_interval)


def _watch_with_watchfiles(
    root: Path,
    on_change: Callable[[list[Path]], None],
    stop: threading.Event,
    file_filter: FileFilter,
) -> None:
    for changes in _watchfiles_watch(root, stop_event=stop, yield_on_timeout=True):
        if not changes:
            continue
        paths = {Path(p).resolve() for _, p in changes}
        filtered = [p for p in paths if file_filter(p)]
        if filtered:
            on_change(filtered)


def _watch_with_polling(
    root: Path,
    on_change: Callable[[list[Path]], None],
    stop: threading.Event,
    file_filter: FileFilter,
    poll_interval: float,
) -> None:
    mtimes: dict[Path, float] = {p: _safe_mtime(p) for p in _iter_files(root, file_filter)}
    while not stop.wait(poll_interval):
        changed: list[Path] = []
        for path in _iter_files(root, file_filter):
            mtime = _safe_mtime(path)
            if mtime is None:
                continue
            old = mtimes.get(path)
            if old is None:
                mtimes[path] = mtime  # first sight: record, don't fire
            elif mtime > old:
                mtimes[path] = mtime
                changed.append(path)
        if changed:
            on_change(changed)


def _iter_files(root: Path, file_filter: FileFilter) -> Iterator[Path]:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        resolved = path.resolve()
        if file_filter(resolved):
            yield resolved


def _safe_mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None
