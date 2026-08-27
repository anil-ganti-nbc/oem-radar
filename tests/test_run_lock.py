"""Single-instance run lock tests.

Covers the OS-level advisory-lock design (fcntl.flock / msvcrt.locking)
that replaced the original PID-liveness check after the 2026-08-23 NAS
canary outage (Diagnostic Clank incident
5f280abf-4bf7-423d-be47-52db5dfb2b72): a crashed run's lock file recorded
pid=1 (its own PID-1 identity inside its Docker PID namespace), and every
subsequent one-shot container -- also PID 1 in its own fresh namespace --
concluded the "old" run was still alive and refused to start, forever.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

from oem_radar.core.run_lock import LockError, RunLock, _pid_alive


def test_acquire_and_release(tmp_path):
    path = tmp_path / "oem-radar.lock"
    lock = RunLock.acquire(path)
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["pid"] == os.getpid()
    lock.release()
    # The lock file is deliberately NOT deleted on release: unlinking it
    # here would race a concurrent acquirer that already opened the old
    # path (classic flock-then-unlink hazard). What matters is that the
    # lock itself is releasable and immediately re-acquirable.
    assert path.exists()
    lock2 = RunLock.acquire(path)
    lock2.release()


def test_context_manager(tmp_path):
    path = tmp_path / "lock"
    with RunLock.acquire(path) as lock:
        assert lock._held
        assert path.exists()
    assert not lock._held
    # re-acquiring immediately after the `with` block proves it was
    # genuinely released, not just that the file is still there
    lock2 = RunLock.acquire(path)
    lock2.release()


def test_duplicate_instance_rejected(tmp_path):
    """Genuine concurrent-owner rejection.

    Two independent `os.open()` calls on the same path -- exactly what two
    separate one-shot containers each opening their own fd on the shared,
    bind-mounted lock file would do -- create two separate open file
    descriptions. flock()/LockFileEx() ties the lock to the open file
    description, not the process or PID, so the second acquire correctly
    fails even though both calls happen inside this single test process.
    """
    path = tmp_path / "lock"
    lock1 = RunLock.acquire(path)
    with pytest.raises(LockError, match="another oem-radar run is active"):
        RunLock.acquire(path)
    lock1.release()
    # after release, acquire works
    lock2 = RunLock.acquire(path)
    lock2.release()


def test_stale_lock_from_crashed_run_recovers_immediately(tmp_path):
    """Reproduces the exact NAS failure end-to-end and proves the fix.

    1. A persisted lock file says pid=1 (as it genuinely did on the NAS:
       the crashed run's own container-namespace PID).
    2. The previous container is gone -- nothing in this test ever holds
       an OS lock on the file, simulating that the crashed process's file
       descriptor (and therefore its flock) was released when it died.
    3. The new one-shot container's own PID is *also* 1 in this
       simulation (patched via os.getpid), exactly reproducing the
       PID-namespace collision that made the old PID-liveness check
       permanently useless.
    4. Sanity-checks that a naive PID-liveness read of the stale file
       would have said "alive" (since pid=1 always exists on any POSIX
       host, e.g. as /sbin/init) -- documenting why the *old* algorithm
       could never have escaped this state on its own.
    5. The corrected implementation ignores the PID field entirely and
       recovers immediately, because nothing holds the OS lock.
    """
    path = tmp_path / "oem-radar.lock"
    path.write_text(json.dumps({
        "pid": 1,
        "hostname": "deploy-oem-radar-run-<stale-container>",
        "started_at": 0,
        "started_at_iso": "2026-08-23T14:45:02Z",
    }))

    # (4) Document the old algorithm's fatal assumption: PID 1 always
    # "looks" alive on a POSIX host (it's /sbin/init, or on some hosts not
    # even signalable -- either way, never a usable staleness signal).
    if sys.platform != "win32":
        assert _pid_alive(1) is not False

    # (3) The new container is also PID 1 in its own namespace.
    with mock.patch("oem_radar.core.run_lock.os.getpid", return_value=1):
        # (2)+(5) No OS lock is actually held on this file (the crashed
        # process's fd is long gone) -- so acquisition succeeds
        # immediately, regardless of the stale pid=1 recorded inside it.
        lock = RunLock.acquire(path)
        assert lock.pid == 1
        assert lock._held

    data = json.loads(path.read_text())
    assert data["pid"] == 1
    assert data["started_at_iso"] != "2026-08-23T14:45:02Z"  # overwritten, fresh
    lock.release()
    assert not lock._held


def test_stale_lock_content_is_diagnostic_only_not_a_gate(tmp_path):
    """A completely unreadable/corrupt lock file must not block recovery
    either -- the file's content is never load-bearing for the decision to
    acquire, only for producing a friendlier error message when the lock
    genuinely is held by someone else."""
    path = tmp_path / "lock"
    path.write_text("not json at all {{{")
    lock = RunLock.acquire(path)
    assert lock._held
    lock.release()


def test_release_is_idempotent_and_survives_external_file_removal(tmp_path):
    path = tmp_path / "lock"
    lock = RunLock.acquire(path)
    if sys.platform != "win32":
        # POSIX allows unlinking a file that a process still has open (the
        # inode survives until the last fd closes) -- simulate that kind of
        # external interference and confirm release() tolerates it. Windows
        # file-sharing semantics don't permit deleting an open file at all,
        # so this specific scenario is POSIX-only; the idempotency
        # assertions below still run on every platform.
        path.unlink()
    lock.release()
    assert not lock._held
    lock.release()  # calling release() twice must be a no-op, not an error


def test_pid_alive_self():
    assert _pid_alive(os.getpid()) is True


def test_radar_config_has_lock_path():
    from oem_radar.core.config import RadarConfig
    cfg = RadarConfig()
    assert cfg.run_lock_path == "data/oem-radar.lock"
