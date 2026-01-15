from dataclasses import dataclass
from typing import List, TYPE_CHECKING
from .utils import run_enroot
if TYPE_CHECKING:
    from .client import EnrootClient
import os
import pathlib
from .config import ENROOT_HOME

@dataclass
class Image:
    id: str
    tags: List[str]


class Images:
    def __init__(self, cli: "EnrootClient"):
        self._cli = cli

    def pull(self, repository: str, tag: str | None = None, registry_host: str = "docker.io") -> Image:
        if tag is None:
            tag = "latest"
        ref = repository.replace("/", "+")
        run_enroot(["import", "--output", os.path.join(ENROOT_HOME, "images", f"{ref}.sqsh"), f"docker://{registry_host}#{repository}:{tag}"], capture=True)
        return self.get(ref)

    def list(self, **_) -> List[Image]:
        data_dir = pathlib.Path(ENROOT_HOME + "/images")
        return [Image(id=str(p), tags=[p.stem])
                for p in data_dir.glob("*.sqsh")]

    def get(self, ref: str) -> Image:
        p = pathlib.Path(ENROOT_HOME + "/images/" + ref + ".sqsh")
        if p.exists():
            return Image(id=str(p), tags=[p.stem])
        for img in self.list():
            if ref in img.tags:
                return img
        raise RuntimeError(f"Image {ref!r} not found")

