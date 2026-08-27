"""Cross-platform single-instance lock for one-shot crawls.

Uses an OS-level advisory file lock (`fcntl.flock` on POSIX, `msvcrt.locking`
on Windows) instead of a PID-liveness check. This is a deliberate fix for a
proven failure mode: every `docker compose run --rm` invocation gets its own
PID namespace, so its main process is *always* PID 1 from its own point of
view. A "is the PID recorded in the old lock file still alive" check
therefore always answers yes when asked by a fresh container -- even when
the process that actually wrote that PID died hours or days ago -- because
the *new* container's own init process trivially satisfies `os.kill(1, 0)`.
That is exactly what happened on the NAS canary: a run crashed mid-crawl on
2026-08-23, left `{"pid": 1, ...}` behind, and every one of the ~81 hourly
scheduler fires since then also *was* PID 1 in its own namespace, so each
one concluded "the old run is still alive" and refused to start -- forever,
with no possible self-recovery. See Diagnostic Clank incident
5f280abf-4bf7-423d-be47-52db5dfb2b72.

An OS lock sidesteps the whole problem: the kernel ties the lock to the
lock file's inode, which is genuinely shared across containers via the
bind-mounted/volume-backed lock file (the same mechanism that already makes
SQLite's own locking correct across separate containers here), and the
kernel releases the lock automatically when the holding process's file
descriptor closes -- for any reason, including a crash or an OOM-kill.
No liveness check, no staleness window, no PID at all is consulted to
decide whether the lock can be acquired.

Ported from Free Game Tracker's `newsroom/run_lock.py` (same architecture,
first proven there) and adapted to preserve OEM Radar's existing
`RunLock.acquire()` / `lock.release()` call-site API, so `crawl_service.py`
and `cli.py` need no changes.

Non-blocking by design: a refusal means "another run is genuinely active
right now," not "wait."
"""

from __future__ import annotations

import json
import logging
import os
import socket
import sys
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("oem_radar.run_lock")

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

_WINDOWS_LOCK_OFFSET = 1 << 20


class LockError(Exception):
    """Raised when the lock is already held by another process."""


def _pid_alive(pid: int) -> bool | None:
    """Best-effort liveness check, retained for diagnostics only.

    NEVER consulted to decide whether a lock can be acquired -- see the
    module docstring for why a PID-liveness check is fundamentally unsound
    across Docker PID namespaces (every container's own main process is
    PID 1 from its own point of view, regardless of what container wrote
    that PID or whether it is still running). This exists only to make
    log/error messages more informative when metadata happens to be
    readable, e.g. "pid=4242" in a LockError.
    """
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes
            SYNCHRONIZE = 0x00100000
            handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            # ERROR_INVALID_PARAMETER (87) usually means PID does not exist
            err = ctypes.windll.kernel32.GetLastError()
            if err in (87, 0):
                return False
            return None
        except Exception:
            return None
    # POSIX
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists but not owned by us
    except Exception:
        return None


def _os_lock(fd: int) -> None:
    if sys.platform == "win32":
        os.lseek(fd, _WINDOWS_LOCK_OFFSET, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _os_unlock(fd: int) -> None:
    if sys.platform == "win32":
        os.lseek(fd, _WINDOWS_LOCK_OFFSET, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)


def _read_holder(path: Path) -> dict | None:
    """Best-effort read of who (probably) holds/held the lock, for a useful
    error message only -- never consulted to decide acquisition."""
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
        return result if isinstance(result, dict) else None
    except Exception:
        return None


@dataclass
class RunLock:
    path: Path
    pid: int
    acquired_at: float
    _fd: int
    _held: bool = False

    @classmethod
    def acquire(cls, path: str | Path) -> "RunLock":
        """Acquire the single-instance run lock, or raise `LockError` immediately.

        Never deletes, overwrites, or otherwise "steals" a lock someone else
        holds, and never guesses at staleness by age or PID -- the kernel is
        the sole judge of whether a prior holder is still alive, via the
        open file descriptor it would still be holding if it were.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        fd = os.open(str(path), os.O_CREAT | os.O_RDWR, 0o644)
        try:
            _os_lock(fd)
        except OSError as exc:
            holder = _read_holder(path)
            os.close(fd)
            if holder:
                detail = (
                    f" (pid={holder.get('pid')}, "
                    f"started={holder.get('started_at_iso')})"
                )
            else:
                detail = ""
            raise LockError(
                f"another oem-radar run is active{detail}, lock={path}. "
                f"Wait for it to finish or stop that process."
            ) from exc

        pid = os.getpid()
        started_at = time.time()
        payload = {
            "pid": pid,
            "hostname": socket.gethostname(),
            "started_at": started_at,
            "started_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        try:
            os.ftruncate(fd, 0)
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, json.dumps(payload, indent=2).encode("utf-8"))
        except OSError:
            # Metadata is diagnostic-only; a write failure must not stop us
            # from holding a lock we have already, genuinely, acquired.
            log.warning("acquired run lock %s but failed to write metadata", path)

        lock = cls(path=path, pid=pid, acquired_at=started_at, _fd=fd, _held=True)
        log.info("acquired run lock %s (pid=%s)", path, pid)
        return lock

    def release(self) -> None:
        if not self._held:
            return
        try:
            _os_unlock(self._fd)
        except OSError as exc:
            log.warning("failed to unlock %s: %s", self.path, exc)
        finally:
            os.close(self._fd)
            self._held = False
            log.info("released run lock %s", self.path)

    def __enter__(self) -> "RunLock":
        return self

    def __exit__(self, *exc) -> None:
        self.release()
