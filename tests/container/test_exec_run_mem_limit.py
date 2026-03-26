"""Integration tests for exec_run(mem_limit=...) using host prlimit before enroot exec."""
import shutil

import pytest

from enroot.container import Container


@pytest.fixture
def ubuntu_container(client):
    """Start an ubuntu container; yield it; kill on teardown."""
    image = client.images.pull("ubuntu", "latest")
    ref = image.tags[0]
    cont = client.containers.run(ref, name=None, detach=True)
    try:
        yield cont
    finally:
        try:
            cont.kill()
        except Exception:
            pass


@pytest.fixture
def alloc_interpreter(ubuntu_container: Container) -> str:
    """Pick an interpreter that can allocate a large contiguous region (for RLIMIT_AS tests)."""
    r = ubuntu_container.exec_run(["sh", "-c", "command -v python3"])
    if r.exit_code == 0:
        return "python3"
    r = ubuntu_container.exec_run(["sh", "-c", "command -v perl"])
    if r.exit_code == 0:
        return "perl"
    pytest.skip(
        "image has neither python3 nor perl; install one in the image to run allocation tests"
    )


requires_prlimit = pytest.mark.skipif(
    shutil.which("prlimit") is None,
    reason="prlimit not in PATH (util-linux)",
)


@requires_prlimit
def test_exec_run_mem_limit_smoke(ubuntu_container: Container):
    """With a generous limit, a trivial command still succeeds (no interpreter needed)."""
    r = ubuntu_container.exec_run(["sh", "-c", "echo ok"], mem_limit="256m")
    assert r.exit_code == 0
    assert b"ok" in r.output


def _oversized_alloc_cmd(which: str):
    if which == "python3":
        return ["python3", "-c", "x = bytearray(256 * 1024 * 1024)"]
    return ["perl", "-e", '$x = "x" x (256 * 1024 * 1024)']


def _moderate_alloc_ok_cmd(which: str):
    if which == "python3":
        return ["python3", "-c", "x = bytearray(16 * 1024 * 1024); print('ok')"]
    return ["perl", "-e", '$x = "x" x (16 * 1024 * 1024); print "ok\n"']


@requires_prlimit
def test_exec_run_mem_limit_rejects_oversized_allocation(
    ubuntu_container: Container, alloc_interpreter: str
):
    """RLIMIT_AS caps address space: a huge allocation fails under a small limit."""
    cmd = _oversized_alloc_cmd(alloc_interpreter)
    r = ubuntu_container.exec_run(cmd, mem_limit="64m")
    print(f"test_exec_run_mem_limit_rejects_oversized_allocation: {r.output}")
    assert r.exit_code != 0, r.output
    assert b"No such file" not in r.output
    assert b"failed to execute" not in r.output


@requires_prlimit
def test_exec_run_mem_limit_same_alloc_ok_without_limit(
    ubuntu_container: Container, alloc_interpreter: str
):
    """Control: moderate allocation succeeds when mem_limit is not applied."""
    cmd = _moderate_alloc_ok_cmd(alloc_interpreter)
    r = ubuntu_container.exec_run(cmd)
    print(f"test_exec_run_mem_limit_same_alloc_ok_without_limit: {r.output}")
    assert r.exit_code == 0, r.output
    assert b"ok" in r.output
