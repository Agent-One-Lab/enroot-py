"""Pytest configuration and fixtures for real enroot integration tests."""
import pytest
from enroot.client import EnrootClient


def _enroot_available():
    return EnrootClient().ping()


@pytest.fixture
def client():
    """Enroot client. Skips test if enroot is not available."""
    c = EnrootClient()
    if not c.ping():
        pytest.skip("enroot not available")
    return c


@pytest.fixture
def running_container(client):
    ref = client.images.pull("alpine", "latest").tags[0]
    container = client.containers.run(ref, name=None, detach=True)
    return container