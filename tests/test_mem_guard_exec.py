"""Unit tests for exec_run(mem_guard_limit=...) wiring (no real enroot)."""

from __future__ import annotations

import asyncio

import pytest

from enroot import errors
from enroot.container import Container


@pytest.fixture
def stub_container(monkeypatch):
    """Minimal container with fake PID so exec_run builds ``enroot exec`` argv."""
    monkeypatch.setattr(Container, "reload", lambda self: None)

    class _Cli:
        pass

    c = Container.__new__(Container)
    c._cli = _Cli()
    c.name = "stub"
    c._port_map = {}
    c._attrs = {}
    c.pids = [12345]
    c._process = None
    c._image_id = None
    c._start_command = None
    c._created_only = False
    c._status = "running"
    return c


def test_exec_run_mem_guard_uses_run_guarded_capture(stub_container, monkeypatch):
    seen: dict = {}

    def fake_run_guarded_capture(cmd, mem_limit, **kwargs):
        seen["cmd"] = cmd
        seen["mem_limit"] = mem_limit
        seen["kwargs"] = kwargs
        assert cmd[:3] == ["enroot", "exec", "12345"]
        return (0, b"ok\n", b"")

    monkeypatch.setattr(
        "enroot.utils.mem_guard.run_guarded_capture",
        fake_run_guarded_capture,
    )

    r = stub_container.exec_run(
        ["echo", "hi"],
        mem_guard_limit="256m",
        mem_guard_poll_interval=0.5,
    )
    assert r.exit_code == 0
    assert r.output == b"ok\n"
    assert seen["mem_limit"] > 0
    assert seen["kwargs"]["poll_interval"] == 0.5
    assert seen["kwargs"]["capture_stdout"] is True


def test_exec_run_async_mem_guard_uses_mem_guard(stub_container, monkeypatch):
    class _FakeGuard:
        def __init__(self, mem_limit_bytes, poll_interval):
            self.mem_limit_bytes = mem_limit_bytes
            self.poll_interval = poll_interval

        async def run_capture(self, cmd, stdout=None, stderr=None):
            assert cmd[:3] == ["enroot", "exec", "12345"]
            return (137, b"", b"killed")

    monkeypatch.setattr(
        "enroot.utils.mem_guard.MemGuard",
        _FakeGuard,
    )

    async def _run():
        return await stub_container.exec_run_async(
            ["sleep", "9"],
            mem_guard_limit="1g",
            mem_guard_poll_interval=2.0,
        )

    with pytest.raises(errors.MemGuardError) as excinfo:
        asyncio.run(_run())
    assert excinfo.value.exit_code == 137
    assert excinfo.value.stderr == b"killed" or b"killed" in (excinfo.value.output or b"")


def test_exec_run_mem_guard_rejects_invalid_limit(stub_container, monkeypatch):
    monkeypatch.setattr(
        "enroot.utils.mem_guard.run_guarded_capture",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not run")),
    )
    with pytest.raises(errors.APIError) as exc:
        stub_container.exec_run("true", mem_guard_limit="not-a-size")
    assert "invalid" in str(exc.value).lower()


def test_exec_run_mem_guard_rejects_zero(stub_container, monkeypatch):
    with pytest.raises(errors.APIError) as exc:
        stub_container.exec_run("true", mem_guard_limit=0)
    assert "positive" in str(exc.value).lower()
