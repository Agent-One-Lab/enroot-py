import pytest
from enroot.container import Containers, Container


def test_list_returns_list(client):
    result = client.containers.list()
    assert isinstance(result, list)
    for c in result:
        assert isinstance(c, Container)
        assert hasattr(c, "name")


def test_get_found(running_container):
    """Get a container that we just started."""
    name = running_container.name
    c = running_container._cli.containers.get(name)
    assert isinstance(c, Container)
    assert c.name == name


def test_get_not_found(client):
    unique_name = "nonexistent-container-xyz-12345"
    with pytest.raises(RuntimeError, match="not found"):
        client.containers.get(unique_name)


def test_run(running_container):
    """Container started by fixture has correct attributes."""
    assert running_container.name
    assert running_container.status == "running"


def test_kill(running_container):
    running_container.kill()
    assert running_container.status == "exited"


def test_remove_force(client):
    """Run a container, then remove with force."""
    image = client.images.pull("alpine", "latest")
    ref = image.tags[0]
    cont = client.containers.run(ref, name=None, detach=True)
    try:
        assert cont.status == "running"
        cont.remove(force=True)
        assert cont.status == "exited"
    finally:
        try:
            cont.kill()
        except Exception:
            pass


def test_exec_run(running_container):
    result = running_container.exec_run("echo hello")
    assert result.exit_code == 0
    assert "hello" in result.output


def test_reload_running(running_container):
    running_container.reload()
    assert running_container.status == "running"
