from __future__ import annotations
from dataclasses import dataclass
from .container import Containers
from .image import Images
from .utils import run_enroot


class EnrootClient:
    def __init__(self):
        self.images = Images(self)
        self.containers = Containers(self)

    def ping(self) -> bool:
        try:
            run_enroot(["version"])
            return True
        except Exception:
            return False

    @property
    def api(self):
        return self

    def close(self):
        pass

def from_env() -> EnrootClient:
    return EnrootClient()
