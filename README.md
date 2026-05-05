# enroot-py

A Python client library for [Enroot](https://github.com/NVIDIA/enroot), providing a docker-py inspired interface for managing Enroot containers and images.

## Overview

`enroot-py` offers a Pythonic API to interact with Enroot, NVIDIA's container runtime for HPC environments. It provides a familiar interface similar to `docker-py`, making it easy to manage containers, pull images, and execute commands within Enroot containers.

## Features

- **Image Management**: Pull, list, and retrieve Docker images converted to Enroot's `.sqsh` format
- **Container Operations**: Create, start, stop, remove, and execute commands in containers
- **Port Mapping**: Automatic port allocation and mapping for containerized services
- **Environment Variables**: Pass environment variables to containers
- **Resource Limits**: CPU and memory limits via `systemd-run` (when available)
- **Docker Compatibility**: Automatically imports Docker images if not found locally

## Prerequisites

- Python 3.8 or higher
- [Enroot](https://github.com/NVIDIA/enroot) installed and available in your `PATH`
- Linux operating system (Enroot is Linux-only)

## Installation

This library is not yet packaged on PyPI. To use it, clone the repository and add it to your `PYTHONPATH`:

```bash
git clone https://github.com/your-username/enroot-py.git
cd enroot-py
export PYTHONPATH=$PYTHONPATH:$(pwd)
```

Alternatively, you can install it in development mode:

```bash
pip install -e .
```

## Quick Start

### Creating a Client

```python
from enroot.client import from_env

client = from_env()

# Check if Enroot is available
if client.ping():
    print("Enroot is running!")
```

### Working with Images

#### Pulling an Image

Pull a Docker image and convert it to Enroot's `.sqsh` format:

```python
# Pull with explicit tag
image = client.images.pull("ubuntu", "20.04")
print(f"Pulled image: {image.id}")

# Pull latest tag (default)
image = client.images.pull("python", "3.9")

# Pull from a custom registry
image = client.images.pull("my-image", "latest", registry_host="registry.example.com")
```

#### Listing Images

```python
images = client.images.list()
for image in images:
    print(f"Image: {image.id}, Tags: {image.tags}")
```

#### Getting a Specific Image

```python
image = client.images.get("ubuntu+20.04")  # Use '+' instead of '/' or ':'
print(f"Found image: {image.id}")
```

### Working with Containers

#### Starting a Container

```python
container = client.containers.run(
    "ubuntu:20.04",              # Image name (will be imported if needed)
    command="sleep 3600",        # Command to run
    name="my-container",         # Optional container name
    detach=True,                 # Required: must be True
    ports={"8080/tcp": "8080"},  # Port mapping (container_port: host_port)
    environment={                # Environment variables
        "MY_VAR": "my_value",
        "DEBUG": "1"
    },
    cpu_count=2.0,              # Optional: CPU limit (requires systemd-run)
    mem_limit="2G"              # Optional: Memory limit (requires systemd-run)
)
print(f"Started container: {container.name}")
print(f"Status: {container.status}")
```

**Note**: `detach=True` is required. Non-detached mode is not currently supported.

#### Using Local .sqsh Files

You can also use local `.sqsh` files directly:

```python
container = client.containers.run(
    "/path/to/image.sqsh",
    command="bash",
    detach=True
)
```

#### Listing Containers

```python
containers = client.containers.list()
for container in containers:
    print(f"- {container.name} ({container.status})")
```

#### Getting a Container

```python
container = client.containers.get("my-container")
print(f"Container status: {container.status}")
print(f"Container attributes: {container.attrs}")
```

#### Executing Commands in a Container

```python
result = container.exec_run("echo 'Hello from container!'")
print(f"Exit code: {result.exit_code}")
print(f"Output: {result.output}")

# Execute with a list of arguments
result = container.exec_run(["ls", "-la", "/tmp"])
```

#### Stopping and Removing Containers

```python
# Stop (kill) a container
container.kill()

# Remove a container
container.remove()

# Force remove a container
container.remove(force=True)
```

#### Checking Container Status

```python
# Reload status from Enroot
container.reload()

# Get current status
status = container.status  # "running" or "exited"

# Get container attributes (including port mappings)
attrs = container.attrs
```

## Configuration

### Environment Variables

- `ENROOT_HOME`: Override the default Enroot home directory (default: `~/.cache/enroot`)
- `ENROOT_IMAGES_PATH`: Override where pulled `.sqsh` images are stored (default: `<ENROOT_HOME>/images`)
- `ENROOT_DEBUG`: Set to `"1"` to enable debug logging (shows Enroot command execution)
- `ENROOT_ASYNC`: Set to `"1"` to make the synchronous `run_enroot` helper transparently use the async backend when no event loop is already running
- `XDG_CACHE_HOME`: Used for cache directory if `ENROOT_HOME` is not set

### Port Mapping

When you specify ports in `containers.run()`, the library automatically allocates a free port on the host and maps it to the container port. The allocated port is available in the container's `attrs`:

```python
container = client.containers.run(
    "nginx",
    detach=True,
    ports={"80/tcp": "80"}
)

# Access port mapping
port_mapping = container.attrs["NetworkSettings"]["Ports"]
# The actual host port is stored here
```

The allocated port is also set as the `PORT` environment variable inside the container.

### Resource Limits

CPU and memory limits are applied using `systemd-run` when available:

```python
container = client.containers.run(
    "my-image",
    detach=True,
    cpu_count=1.5,      # 1.5 CPUs
    mem_limit="512M"    # 512 MB memory limit
)
```

**Note**: Resource limits require `systemd-run` to be available. If it's not found, a warning is issued and the limits are ignored.

## API Reference

### `EnrootClient`

Main client class for interacting with Enroot.

- `ping() -> bool`: Check if Enroot is available
- `images`: Access to image operations (`Images` instance)
- `containers`: Access to container operations (`Containers` instance)

### `Images`

Image management operations.

- `pull(repository: str, tag: str | None = None, registry_host: str = "", directory: str | None = None) -> Image`: Pull and import a Docker image. When `registry_host` is empty (the default), Enroot uses its built-in default registry; pass e.g. `"registry.example.com"` to override.
- `list() -> List[Image]`: List all available images
- `get(ref: str) -> Image`: Get a specific image by reference

### `Containers`

Container management operations.

- `run(image, command=None, name=None, timeout=120, detach=False, remove=False, ports=None, mount=None, environment=None, cpu_count=None, mem_limit=None, cpus=None, **_) -> Container`: Create and start a container (`detach=True` is required).
- `create(image, command=None, name=None, ports=None, mount=None, environment=None, cpu_count=None, mem_limit=None, cpus=None, timeout=120, **_) -> Container`: Create a container without starting it (similar to `docker create`). The optional `command` is stashed and used as the default for `Container.start(...)`.
- `create_async(...) -> Container`: Coroutine variant of `create`.
- `list() -> List[Container]`: List all containers
- `get(ident: str) -> Container`: Get a container by name

### `Container`

Represents a single container instance.

- `name: str` / `id: str` / `short_id: str`: Container identifiers (Enroot uses the name as the id).
- `status: str`: Container status (`"created"`, `"running"`, or `"exited"`).
- `attrs: Dict`: Container attributes (similar to Docker API).
- `pids: List[int]`: Cached in-container PIDs from `enroot list --fancy`.
- `reload()` / `reload_async()`: Refresh state from `enroot list`.
- `start(command=None, environment=None, mount=None, cpu_count=None, mem_limit=None, cpus=None, timeout=30, **_)`: Start a container previously created with `containers.create(...)`.
- `start_async(...)`: Async variant of `start`.
- `stop(timeout=10, **_)`: Gracefully stop and remove the container.
- `kill(**_)` / `kill_async(timeout=10, **_)`: Forcefully stop and remove.
- `remove(force=False, **_)`: Remove the container via `enroot remove`.
- `exec_run(cmd, *, stdout=True, stderr=True, demux=False, workdir=None, user=None, environment=None, detach=False, mem_limit=None, mem_guard_limit=None, mem_guard_poll_interval=1.0, timeout=None, **_) -> ExecResult`: Execute a command in the container. Supports host-side `timeout` (raises `enroot.errors.TimeoutError` on exit 124), prlimit-based `mem_limit`, and psutil-based RSS cap `mem_guard_limit` (raises `enroot.errors.MemGuardError` on exit 137).
- `exec_run_async(...) -> ExecResult`: Async variant of `exec_run`.
- `copy_to(local_path, container_path)` / `put_archive(path, data)`: Copy files into a running container.

### `Image`

Represents a container image.

- `id: str`: Image ID (path to .sqsh file)
- `tags: List[str]`: Image tags

## Limitations

- **Detached Mode Only**: The `detach` parameter must be `True`. Non-detached containers are not supported.
- **No Logs**: The `logs()` method returns an empty bytes object. Enroot doesn't provide a built-in logging mechanism.
- **Resource Limits**: CPU and memory limits require `systemd-run` to be available on the system.
- **Port Mapping**: All ports are mapped to a single automatically-allocated free port. Individual port mappings are not fully supported.

## Testing

The test suite uses [pytest](https://docs.pytest.org/). Install the dev extras and run it:

```bash
pip install -e ".[dev]"
pytest
```

Slow integration checks that pull large images are gated behind the `slow` marker:

```bash
pytest -m slow
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

MIT License (see `pyproject.toml` for details)

## Related Projects

- [Enroot](https://github.com/NVIDIA/enroot) - The underlying container runtime
- [docker-py](https://github.com/docker/docker-py) - The inspiration for this library's API design
