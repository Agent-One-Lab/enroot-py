import os
import shutil
import signal
import subprocess
import time
import asyncio
import pytest
from enroot import config as enroot_config
from enroot import errors
import enroot.utils.utils as utils_impl
from enroot.utils import (
    clear_enroot_containers,
    container_process_groups,
    stop_process_groups,
    random_name,
    parse_list,
    systemd_prefix,
    mem_limit_to_bytes,
    list_containers_plain_async,
    list_containers_fancy_async,
)


def test_random_name():
    name = random_name()
    assert name.startswith("cnt-")
    assert len(name) == 12  # "cnt-" + 8 hex chars

    name = random_name(prefix="test")
    assert name.startswith("test-")
    assert len(name) == 13  # "test-" + 8 hex chars


def test_parse_list_simple():
    text = """
        container1
        container2
        """
    parsed = parse_list(text)
    assert list(parsed.keys()) == ["container1", "container2"]


def test_parse_list_fancy():
    text = """
NAME      PID       STATE     STARTED      TIME      MNTNS      USERNS    COMMAND
my-cont   12345     running   2 hours ago  0.01s     402653     402653    /bin/bash
        """
    parsed = parse_list(text)
    assert "my-cont" in parsed
    assert parsed["my-cont"]["pids"] == [12345]
    assert parsed["my-cont"]["state"] == "running"


def test_mem_limit_to_bytes():
    assert mem_limit_to_bytes(1024) == 1024
    assert mem_limit_to_bytes("1024") == 1024
    assert mem_limit_to_bytes("512k") == 512 * 1024
    assert mem_limit_to_bytes("2m") == 2 * 1024**2
    assert mem_limit_to_bytes("1G") == 1024**3
    assert mem_limit_to_bytes("0") == 0


def test_systemd_prefix_no_limits():
    assert systemd_prefix(None, None) == []


@pytest.mark.skipif(shutil.which("systemd-run") is None, reason="systemd-run not found")
def test_systemd_prefix_with_limits():
    prefix = systemd_prefix(2, "1G")
    assert "systemd-run" in prefix
    assert "CPUQuota=200%" in prefix
    assert "MemoryMax=1G" in prefix


@pytest.mark.skipif(shutil.which("systemd-run") is None, reason="systemd-run not found")
def test_systemd_prefix_with_only_cpu():
    prefix = systemd_prefix(0.5, None)
    assert "systemd-run" in prefix
    assert "CPUQuota=50%" in prefix
    assert "MemoryMax=1G" not in ' '.join(prefix)


@pytest.mark.skipif(shutil.which("systemd-run") is None, reason="systemd-run not found")
def test_systemd_prefix_with_only_mem():
    prefix = systemd_prefix(None, 512)
    assert "systemd-run" in prefix
    assert "CPUQuota" not in ' '.join(prefix)
    assert "MemoryMax=512" in prefix


def test_run_enroot_timeout_exit_124_maps_to_errors_timeout(monkeypatch):
    """Host ``timeout`` exits 124; run_enroot maps that to errors.TimeoutError."""

    class FakeResult:
        returncode = 124
        stdout = ""
        stderr = ""

    monkeypatch.setattr(enroot_config, "ENROOT_ASYNC", False)
    monkeypatch.setattr(utils_impl.subprocess, "run", lambda *a, **k: FakeResult())
    with pytest.raises(errors.TimeoutError, match="timed out"):
        utils_impl.run_enroot(["list"], timeout=5.0, check=True)


def test_host_argv_with_timeout_wraps_full_command():
    w = utils_impl._host_argv_with_timeout(["srun", "enroot", "list"], 3.5)
    assert w[0] == "sh" and w[1] == "-c"
    assert "timeout 4 sh -c" in w[2]
    assert "srun" in w[2] and "enroot" in w[2]


def test_list_containers_plain_async_uses_run_enroot_async(monkeypatch):
    async def fake_run_enroot_async(*args, **kwargs):
        return "c1\nc2\n"

    monkeypatch.setattr(utils_impl, "run_enroot_async", fake_run_enroot_async)
    out = asyncio.run(list_containers_plain_async())
    assert "c1" in out and "c2" in out


def test_list_containers_fancy_async_fallbacks_to_plain(monkeypatch):
    async def fake_run_enroot_async(args, **kwargs):
        if args == ["list", "--fancy"]:
            raise RuntimeError("fancy failed")
        return "plain-only\n"

    monkeypatch.setattr(utils_impl, "run_enroot_async", fake_run_enroot_async)
    out = asyncio.run(list_containers_fancy_async(retries=1, fallback_plain=True))
    assert "plain-only" in out


class _FakeEnrootHost:
    """In-memory stand-in for ``enroot list [--fancy]`` / ``enroot remove`` on one host."""

    def __init__(self, names, refuse=(), pids=None):
        self.names = list(names)
        self.refuse = set(refuse)  # names whose removal fails (they stay listed)
        self.pids = dict(pids or {})  # name -> init pid (no pid: not running)
        self.calls = []

    def run_enroot(self, args, capture=True, check=True, text=True, timeout=None):
        self.calls.append(list(args))
        if args == ["list"]:
            return "\n".join(self.names) + ("\n" if self.names else "")
        if args == ["list", "--fancy"]:
            rows = ["NAME                PID       COMM"]
            rows += [f"{name:<20}{self.pids.get(name, ''):<10}{'sh' if name in self.pids else ''}" for name in self.names]
            return "\n".join(rows) + "\n"
        assert args[:2] == ["remove", "--force"] and len(args) == 3, args
        name = args[2]
        if name in self.refuse:
            if check:
                raise RuntimeError(f"enroot remove failed for {name}")
            return ""
        self.names.remove(name)
        return ""


@pytest.fixture
def fake_host(monkeypatch):
    def _install(names, **kw):
        host = _FakeEnrootHost(names, **kw)
        monkeypatch.setattr(enroot_config, "ENROOT_ASYNC", False)
        monkeypatch.setattr(utils_impl, "run_enroot", host.run_enroot)
        # Every pid is its own session leader; stopping records the groups instead of signalling.
        host.stopped = []
        monkeypatch.setattr(utils_impl, "container_process_groups", lambda pids: set(pids))
        monkeypatch.setattr(utils_impl, "stop_process_groups",
                            lambda pgids, timeout=10.0: host.stopped.append((sorted(pgids), list(host.names))))
        return host
    return _install


def test_clear_enroot_containers_without_prefix_removes_everything(fake_host):
    host = fake_host(["b-2", "a-1", "c-3"])
    assert clear_enroot_containers() == ["b-2", "a-1", "c-3"]
    assert host.names == []


def test_clear_enroot_containers_prefix_removes_only_matching(fake_host):
    host = fake_host(["agentfly-a", "res-1", "agentfly-b", "0f626053-74f7", "agentflyx"])
    assert clear_enroot_containers(prefix="agentfly-") == ["agentfly-a", "agentfly-b"]
    assert host.names == ["res-1", "0f626053-74f7", "agentflyx"]
    removes = [c for c in host.calls if c[0] == "remove"]
    assert removes == [["remove", "--force", "agentfly-a"], ["remove", "--force", "agentfly-b"]]


def test_clear_enroot_containers_nothing_to_do_makes_no_remove_calls(fake_host):
    host = fake_host(["res-1"])
    assert clear_enroot_containers(prefix="agentfly-") == []
    assert [c for c in host.calls if c[0] == "remove"] == []


def test_clear_enroot_containers_keeps_sweeping_past_a_failure(fake_host):
    host = fake_host(["agentfly-a", "agentfly-b", "agentfly-c"], refuse={"agentfly-b"})
    assert clear_enroot_containers(prefix="agentfly-") == ["agentfly-a", "agentfly-c"]
    assert host.names == ["agentfly-b"]
    assert len([c for c in host.calls if c[0] == "remove"]) == 3


def test_clear_enroot_containers_survives_a_raising_remove(fake_host):
    host = fake_host(["agentfly-a", "agentfly-b"])
    real = host.run_enroot

    def run_enroot(args, **kw):
        if args[-1] == "agentfly-a":
            raise OSError("enroot: command not found")
        return real(args, **kw)

    utils_impl.run_enroot = run_enroot  # fake_host's monkeypatch restores it
    assert clear_enroot_containers(prefix="agentfly-") == ["agentfly-b"]


def test_clear_enroot_containers_stops_running_matching_containers_before_removal(fake_host):
    host = fake_host(["agentfly-a", "res-1", "agentfly-b", "agentfly-idle"],
                     pids={"agentfly-a": 101, "res-1": 202, "agentfly-b": 303})
    assert clear_enroot_containers(prefix="agentfly-") == ["agentfly-a", "agentfly-b", "agentfly-idle"]
    # One stop call, for the matching running containers only, while all were still listed.
    assert host.stopped == [([101, 303], ["agentfly-a", "res-1", "agentfly-b", "agentfly-idle"])]


def _spawn_session_with_children():
    """A stand-in container: a session leader that backgrounds two children."""
    proc = subprocess.Popen(["sh", "-c", "sleep 1000 & sleep 1001 & wait"], start_new_session=True)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        children = [pid for pid in _group_members(proc.pid) if pid != proc.pid]
        if len(children) == 2:
            return proc, children
        time.sleep(0.05)
    raise AssertionError("children did not start")


def _group_members(pgid):
    """Non-zombie processes in group ``pgid``."""
    members = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat") as f:
                fields = f.read().rsplit(")", 1)[1].split()
        except OSError:
            continue
        if fields[0] != "Z" and int(fields[2]) == pgid:
            members.append(int(entry))
    return members


def test_stop_process_groups_stops_background_children():
    proc, children = _spawn_session_with_children()
    try:
        stop_process_groups([proc.pid], timeout=5)
        proc.wait(timeout=5)
        assert _group_members(proc.pid) == []
    finally:
        for pid in children:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_orphaned_children_are_found_and_stopped_after_init_died():
    proc, children = _spawn_session_with_children()
    try:
        proc.kill()  # what terminating only the start process used to do
        proc.wait(timeout=5)
        assert sorted(_group_members(proc.pid)) == sorted(children)
        assert container_process_groups(children) == {proc.pid}
        stop_process_groups(container_process_groups(children), timeout=5)
        assert _group_members(proc.pid) == []
    finally:
        for pid in children:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_callers_own_group_and_session_are_never_targeted():
    assert container_process_groups([os.getpid()]) == set()
    stop_process_groups([os.getpgrp()], timeout=0.1)  # would kill this test run if signalled
    assert container_process_groups([2 ** 22 + 12345]) == set()  # no such process
