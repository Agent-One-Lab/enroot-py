"""Integration tests for exec_run(timeout=...) — host ``timeout`` wraps ``enroot exec``."""
import time

import pytest

from enroot.container import Container


def test_exec_run_timeout_stops_long_sleep(running_container: Container):
    """Long sleep is cut short by host ``timeout`` wrapping the full exec (not ~60s)."""
    t0 = time.monotonic()
    with pytest.raises(TimeoutError, match="exec_run timed out"):
        running_container.exec_run(["sleep", "60"], timeout=2)
    elapsed = time.monotonic() - t0
    assert elapsed < 15, f"expected quick return, took {elapsed:.1f}s"


def test_exec_run_timeout_with_workdir(running_container: Container):
    """timeout wraps the full argv including workdir shell wrapper."""
    r = running_container.exec_run("pwd", workdir="/tmp", timeout=30)
    assert r.exit_code == 0
    assert b"/tmp" in r.output
