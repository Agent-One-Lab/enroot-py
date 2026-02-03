import pathlib
import pytest
from enroot.image import Images, Image
from enroot.client import EnrootClient
from enroot import ENROOT_HOME


def test_list_returns_list(client):
    result = client.images.list()
    assert isinstance(result, list)
    for img in result:
        assert isinstance(img, Image)
        assert hasattr(img, "id")
        assert hasattr(img, "tags")


def test_pull(client):
    image = client.images.pull("alpine", "latest")
    assert isinstance(image, Image)
    assert "alpine" in image.tags
    assert image.id.endswith(".sqsh")
    assert pathlib.Path(image.id).exists()


def test_get_exists_after_pull(client):
    client.images.pull("alpine", "latest")
    image = client.images.get("alpine")
    assert image.tags == ["alpine"]
    assert image.id == str(pathlib.Path(ENROOT_HOME, "images", "alpine.sqsh"))


def test_get_not_found(client):
    unique_name = "nonexistent-image-name-xyz-12345"
    with pytest.raises(RuntimeError, match="not found"):
        client.images.get(unique_name)
