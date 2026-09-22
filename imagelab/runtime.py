"""Runtime safeguards for supervised Mac Image Lab services."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Protocol


class SleepAssertion(Protocol):
    def set_active(self, active: bool) -> None: ...
    def release(self) -> None: ...


class Process(Protocol):
    def poll(self) -> int | None: ...
    def terminate(self) -> None: ...
    def wait(self, timeout: float | None = None) -> int: ...
    def kill(self) -> None: ...


class NullIdleSleepAssertion:
    """Test/library default; production entry points opt into caffeinate."""

    active = False

    def set_active(self, _active: bool) -> None:
        return

    def release(self) -> None:
        return


class IdleSleepAssertion:
    """Prevent idle system sleep only while this worker owns active work."""

    def __init__(self, process_factory: Callable[..., Process] = subprocess.Popen):
        self._process_factory = process_factory
        self._process: Process | None = None

    @property
    def active(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def set_active(self, active: bool) -> None:
        if active:
            if not self.active:
                self._process = self._process_factory(
                    ["/usr/bin/caffeinate", "-i", "-w", str(os.getpid())],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            return
        self.release()

    def release(self) -> None:
        process = self._process
        self._process = None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)

    def __enter__(self) -> "IdleSleepAssertion":
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()


def rotate_logs_copytruncate(log_dir: Path, *, max_bytes: int = 10 * 1024 * 1024, backups: int = 3) -> list[Path]:
    """Bound launchd log files without replacing their open file descriptors."""
    if max_bytes < 1 or backups < 1:
        raise ValueError("max_bytes and backups must be positive")
    rotated: list[Path] = []
    directory = Path(log_dir)
    if not directory.exists():
        return rotated
    for path in sorted(directory.glob("*.log")):
        if not path.is_file() or path.is_symlink() or path.stat().st_size <= max_bytes:
            continue
        oldest = path.with_name(f"{path.name}.{backups}")
        oldest.unlink(missing_ok=True)
        for number in range(backups - 1, 0, -1):
            source = path.with_name(f"{path.name}.{number}")
            if source.exists():
                source.replace(path.with_name(f"{path.name}.{number + 1}"))
        first = path.with_name(f"{path.name}.1")
        shutil.copy2(path, first)
        with path.open("r+b") as handle:
            handle.truncate(0)
        rotated.append(path)
    return rotated
