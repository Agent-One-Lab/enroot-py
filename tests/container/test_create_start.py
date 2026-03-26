"""Tests for Containers.create() and Container.start()."""
import pytest
from enroot.container import Container
from enroot import errors


@pytest.fixture
def alpine_image(client):
    """Pull alpine once for create/start tests."""
    return client.images.pull("alpine", "latest")


@pytest.fixture
def created_container(client, alpine_image):
    """Create a container (not started); yield it; kill/remove on teardown."""
    ref = alpine_image.tags[0]
    cont = client.containers.create(ref, name=None, command="sleep 3600")
    try:
        yield cont
    finally:
        try:
            cont.kill()
        except Exception:
            try:
                cont.remove(force=True)
            except Exception:
                pass


def test_create_returns_container(client, alpine_image):
    """create() returns a Container with status 'created' and valid name/id."""
    ref = alpine_image.tags[0]
    cont = client.containers.create(ref, name=None)
    try:
        assert isinstance(cont, Container)
        assert cont.name
        assert cont.id == cont.name
        assert cont.short_id == cont.id[:12]
        assert cont.status == "created"
        assert cont.attrs.get("State", {}).get("Status") == "created"
        assert cont.attrs.get("State", {}).get("Running") is False
    finally:
        try:
            cont.kill()
        except Exception:
            cont.remove(force=True)


def test_create_with_name(client, alpine_image):
    """create(name=...) uses the given name."""
    ref = alpine_image.tags[0]
    name = "test-create-name-xyz"
    cont = client.containers.create(ref, name=name)
    try:
        assert cont.name == name
        assert cont.id == name
    finally:
        cont.kill()


def test_start_after_create(created_container: Container):
    """create() then start(): container becomes running and exec_run works."""
    cont = created_container
    assert cont.status == "created"
    cont.start()
    try:
        assert cont.status == "running"
        result = cont.exec_run("echo hello")
        assert result.exit_code == 0
        assert b"hello" in result.output
    finally:
        cont.kill()  # stops and removes


def test_start_with_command(client, alpine_image):
    """create() then start(command=...): command is run and container stays up."""
    ref = alpine_image.tags[0]
    cont = client.containers.create(ref, name=None)
    try:
        cont.start(command="sleep 3600")
        assert cont.status == "running"
        result = cont.exec_run("echo ok")
        assert result.exit_code == 0
        assert b"ok" in result.output
    finally:
        cont.kill()


def test_create_then_start_uses_stored_command(client, alpine_image):
    """create(..., command=...) then start() uses that command (container stays running)."""
    ref = alpine_image.tags[0]
    cont = client.containers.create(ref, name=None, command="sleep 3600")
    try:
        cont.start()
        assert cont.status == "running"
        cont.exec_run("echo from container")
    finally:
        cont.kill()


def test_create_duplicate_name_raises(client, alpine_image):
    """create(name=X) when a running container has name X raises APIError."""
    ref = alpine_image.tags[0]
    name = "test-dup-name-xyz"
    cont = client.containers.create(ref, name=name)
    try:
        cont.start(command="sleep 3600")
        with pytest.raises(errors.APIError, match="already running"):
            client.containers.create(ref, name=name)
    finally:
        cont.kill()


def test_get_after_start(client, alpine_image):
    """After create() and start(), containers.get(name) returns the running container."""
    ref = alpine_image.tags[0]
    cont = client.containers.create(ref, name=None, command="sleep 3600")
    try:
        cont.start()
        name = cont.name
        found = client.containers.get(name)
        assert found.name == name
        assert found.status == "running"
    finally:
        cont.kill()


def test_start_timeout_raises_timeout_error(created_container: Container):
    """start(timeout=0) raises TimeoutError if container is not observed as running in time."""
    cont = created_container
    with pytest.raises(errors.TimeoutError, match="did not appear in 'enroot list'"):
        cont.start(timeout=0)
