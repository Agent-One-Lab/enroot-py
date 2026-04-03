import shutil
import asyncio
import pytest
from enroot import config as enroot_config
from enroot import errors
from enroot import utils as enroot_utils
from enroot.utils import (
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
    monkeypatch.setattr(enroot_utils.subprocess, "run", lambda *a, **k: FakeResult())
    with pytest.raises(errors.TimeoutError, match="timed out"):
        enroot_utils.run_enroot(["list"], timeout=5.0, check=True)


def test_host_argv_with_timeout_wraps_full_command():
    w = enroot_utils._host_argv_with_timeout(["srun", "enroot", "list"], 3.5)
    assert w[0] == "sh" and w[1] == "-c"
    assert "timeout 4 sh -c" in w[2]
    assert "srun" in w[2] and "enroot" in w[2]


def test_list_containers_plain_async_uses_run_enroot_async(monkeypatch):
    async def fake_run_enroot_async(*args, **kwargs):
        return "c1\nc2\n"

    monkeypatch.setattr(enroot_utils, "run_enroot_async", fake_run_enroot_async)
    out = asyncio.run(list_containers_plain_async())
    assert "c1" in out and "c2" in out


def test_list_containers_fancy_async_fallbacks_to_plain(monkeypatch):
    async def fake_run_enroot_async(args, **kwargs):
        if args == ["list", "--fancy"]:
            raise RuntimeError("fancy failed")
        return "plain-only\n"

    monkeypatch.setattr(enroot_utils, "run_enroot_async", fake_run_enroot_async)
    out = asyncio.run(list_containers_fancy_async(retries=1, fallback_plain=True))
    assert "plain-only" in out
