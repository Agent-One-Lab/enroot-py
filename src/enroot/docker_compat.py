"""
Docker-py compatible namespace so that sys.modules["docker"] = enroot.docker_compat works.

Use: import enroot.docker_compat; sys.modules["docker"] = enroot.docker_compat
Then: docker.from_env(), from docker.models.containers import Container, docker.errors
"""

import types

from .client import from_env, EnrootClient
from .container import Container, Containers
from . import errors

# Build docker.models.containers so "from docker.models.containers import Container" works
_containers = types.ModuleType("docker.models.containers")
_containers.Container = Container
_containers.Containers = Containers

_models = types.ModuleType("docker.models")
_models.containers = _containers

# DockerClient is the docker-py class name; alias so "from docker import DockerClient" works.
DockerClient = EnrootClient

# Attach to this module so sys.modules["docker"] has from_env, models, errors
models = _models

__all__ = ["from_env", "EnrootClient", "DockerClient", "models", "errors", "Container", "Containers"]
