"""Tests for exec_run workdir and user (using ubuntu image)."""
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


def test_exec_run_workdir(ubuntu_container: Container):
    """exec_run with workdir runs the command in that directory."""
    result = ubuntu_container.exec_run("pwd", workdir="/tmp")
    assert result.exit_code == 0
    out = result.output.decode().strip()
    assert out == "/tmp", f"Expected /tmp, got {out!r}"


def test_exec_run_workdir_subdir(ubuntu_container: Container):
    """exec_run with workdir=/var works."""
    result = ubuntu_container.exec_run("pwd", workdir="/var")
    assert result.exit_code == 0
    out = result.output.decode().strip()
    assert out == "/var", f"Expected /var, got {out!r}"


def test_exec_run_user_accepted_ignored(ubuntu_container: Container):
    """user= is accepted but has no effect; command still runs."""
    result = ubuntu_container.exec_run("echo ok", user="root")
    assert result.exit_code == 0
    assert b"ok" in result.output


def test_exec_run_workdir_and_user(ubuntu_container: Container):
    """exec_run with workdir and user=: workdir applies, user= is ignored."""
    result = ubuntu_container.exec_run(
        ["sh", "-c", "pwd && whoami"],
        workdir="/tmp",
        user="nobody",
    )
    assert result.exit_code == 0
    out = result.output.decode().strip()
    lines = [s.strip() for s in out.splitlines()]
    assert "/tmp" in lines, f"Expected /tmp in {lines}"
    # whoami returns effective user (user= is ignored)
