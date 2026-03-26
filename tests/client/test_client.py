import pytest
from enroot.client import EnrootClient, from_env


def test_from_env():
    client = from_env()
    assert isinstance(client, EnrootClient)


def test_ping_returns_bool():
    client = EnrootClient()
    result = client.ping()
    assert isinstance(result, bool)


def test_ping_success(client):
    """When enroot is available, ping() returns True."""
    assert client.ping() is True
