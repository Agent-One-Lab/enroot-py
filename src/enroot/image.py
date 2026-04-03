from dataclasses import dataclass
import logging
import os
import pathlib
from pathlib import Path
from typing import List, TYPE_CHECKING

from . import errors
from .config import ENROOT_IMAGES_PATH
from .utils import run_enroot

if TYPE_CHECKING:
    from .client import EnrootClient

logger = logging.getLogger("enroot.image")

@dataclass
class Image:
    """An Enroot image reference.

    Attributes:
        id: Path to the ``.sqsh`` file on disk.
        tags: Logical tags associated with this image (for example, ``\"alpine\"``,
            ``\"pytorch+2.2.2-cpu\"``).
    """

    id: str
    tags: List[str]


def pull_image(
    repository: str,
    tag: str | None = None,
    registry_host: str = "",
    directory: str = None,
) -> Image:
    """Import/pull an image into Enroot storage.

    Args:
        repository: Docker image repository, for example ``\"alpine\"`` or
            ``\"pytorch/pytorch\"``.
        tag: Optional tag name.
        registry_host: Optional registry prefix (used to build ``docker://...``).
        directory: Optional destination directory for the resulting ``.sqsh`` file.

    Returns:
        An :class:`Image` describing the pulled/imported image.
    """
    if registry_host == "":
        repository_full = f"docker://{repository}"
    else:
        repository_full = f"docker://{registry_host}#{repository}"

    if tag is not None:
        repository_full += f":{tag}"
    
    ref = repository.replace("/", "+").replace(":", "+")

    logger.debug(
        "ENROOT_IMAGES_PATH const=%r env=%r",
        ENROOT_IMAGES_PATH,
        os.getenv("ENROOT_IMAGES_PATH"),
    )

    destination = os.path.join(directory or ENROOT_IMAGES_PATH, f"{ref}.sqsh")
    parent_dir = Path(destination).parent
    if not os.path.exists(parent_dir):
        os.makedirs(parent_dir, exist_ok=True)

    
    if not os.path.exists(destination):
        logger.info("Pulling image %s to %s", repository_full, destination)
        run_enroot(["import", "--output", destination, repository_full], capture=True, check=True)
    else:
        logger.info("Image %s already exists at %s", repository_full, destination)

    return Image(id=str(destination), tags=[ref])

class Images:
    """Collection wrapper exposed as ``client.images``."""
    def __init__(self, cli: "EnrootClient"):
        self._cli = cli

    def pull(self, repository: str, tag: str = None, registry_host: str = "", directory: str = None) -> Image:
        """Pull/import an image into Enroot storage.

        Args:
            repository: Docker image repository.
            tag: Optional tag name.
            registry_host: Optional registry prefix.
            directory: Optional destination directory for the resulting ``.sqsh``.

        Returns:
            The resulting :class:`Image`.
        """

        image = pull_image(repository, tag, registry_host, directory)
        return image

    def list(self, **_) -> List[Image]:
        """List images stored in ``ENROOT_IMAGES_PATH``.

        Returns:
            A list of :class:`Image` objects discovered under ``ENROOT_IMAGES_PATH``.
        """
        data_dir = pathlib.Path(ENROOT_IMAGES_PATH)
        return [Image(id=str(p), tags=[p.stem])
                for p in data_dir.glob("*.sqsh")]

    def get(self, ref: str) -> Image:
        """Get an image by tag or reference.

        Searches for ``<ref>.sqsh`` first, then falls back to scanning image tags.

        Args:
            ref: Logical image reference or tag.

        Returns:
            The matching :class:`Image`.

        Raises:
            RuntimeError: If no image matching ``ref`` can be found.
        """
        p = pathlib.Path(ENROOT_IMAGES_PATH + "/" + ref + ".sqsh")
        if p.exists():
            return Image(id=str(p), tags=[p.stem])
        for img in self.list():
            if ref in img.tags:
                return img
        # Tests expect a generic RuntimeError for missing images.
        raise RuntimeError(f"Image {ref!r} not found")

