from dataclasses import dataclass
from typing import List, TYPE_CHECKING
from .utils import run_enroot
from . import errors
if TYPE_CHECKING:
    from .client import EnrootClient
import os
import pathlib
from .config import ENROOT_IMAGES_PATH
from pathlib import Path

@dataclass
class Image:
    id: str
    tags: List[str]


def pull_image(repository: str, tag: str | None = None, registry_host: str = "", directory: str = None) -> Image:
    if registry_host == "":
        repository_full = f"docker://{repository}"
    else:
        repository_full = f"docker://{registry_host}#{repository}"

    if tag is not None:
        repository_full += f":{tag}"
    
    ref = repository.replace("/", "+").replace(":", "+")

    print(f"ENROOT_IMAGES_PATH const: {ENROOT_IMAGES_PATH}")
    print(f"ENROOT_IMAGES_PATH env  : {os.getenv('ENROOT_IMAGES_PATH')}")

    destination = os.path.join(directory or ENROOT_IMAGES_PATH, f"{ref}.sqsh")
    parent_dir = Path(destination).parent
    if not os.path.exists(parent_dir):
        os.makedirs(parent_dir, exist_ok=True)

    
    if not os.path.exists(destination):
        print(f"Pulling image {repository_full} to {destination}")
        run_enroot(["import", "--output", destination, repository_full], capture=True, check=True)
    else:
        print(f"Image {repository_full} already exists in {destination}")

    return Image(id=str(destination), tags=[ref])

class Images:
    def __init__(self, cli: "EnrootClient"):
        self._cli = cli

    def pull(self, repository: str, tag: str = None, registry_host: str = "", directory: str = None) -> Image:

        image = pull_image(repository, tag, registry_host, directory)
        return image

    def list(self, **_) -> List[Image]:
        data_dir = pathlib.Path(ENROOT_IMAGES_PATH)
        return [Image(id=str(p), tags=[p.stem])
                for p in data_dir.glob("*.sqsh")]

    def get(self, ref: str) -> Image:
        p = pathlib.Path(ENROOT_IMAGES_PATH + "/" + ref + ".sqsh")
        if p.exists():
            return Image(id=str(p), tags=[p.stem])
        for img in self.list():
            if ref in img.tags:
                return img
        # Tests expect a generic RuntimeError for missing images.
        raise RuntimeError(f"Image {ref!r} not found")

