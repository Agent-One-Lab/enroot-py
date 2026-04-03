# API Usage Examples

This page focuses on synchronous APIs and common arguments such as
`mem_limit`, `timeout`, and `copy_to`.

## 1) Lifecycle with resource limits

```python
from enroot import from_env

client = from_env()
img = client.images.pull("alpine", "latest")

container = client.containers.create(
    image=img.tags[0],
    name="demo-api-usage",
    command="sleep 600",
)

container.start(
    environment={"APP_ENV": "dev"},
    cpu_count=1.0,
    mem_limit="512m",
    timeout=30,
)

print(container.status)   # running / created / exited
print(container.attrs)    # docker-py-like metadata
```

## 2) `exec_run` with environment, workdir, and timeout

```python
from enroot import errors

try:
    result = container.exec_run(
        cmd="sh -lc 'pwd && echo $MY_FLAG && sleep 2'",
        workdir="/",
        environment={"MY_FLAG": "enabled"},
        timeout=1,   # host-side timeout via timeout(1)
    )
    print(result.exit_code)
    print(result.output.decode("utf-8", errors="replace"))
except errors.TimeoutError:
    print("Command timed out")
```

## 3) `exec_run` with memory limit

```python
result = container.exec_run(
    cmd="python - <<'PY'\na=[0]*10_000_000\nprint('ok')\nPY",
    mem_limit="256m",  # applies prlimit --as before enroot exec
)
print(result.exit_code)
```

## 4) Copy files into container with `copy_to`

```python
# Copy local file/dir into the running container.
container.copy_to(local_path="./configs", container_path="/tmp")

check = container.exec_run("ls -la /tmp")
print(check.output.decode("utf-8", errors="replace"))
```

## 5) Stop and cleanup

```python
container.stop(timeout=5)
container.remove(force=True)
```

## Notes

- Resource-limit arguments passed to `containers.create(...)` are compatibility
  arguments for docker-style APIs and do not enforce limits at create time.
  Apply limits when starting/running containers (for example via `start(..., mem_limit=..., cpu_count=...)`).
- `start(..., timeout=...)` waits for the container to appear in `enroot list`.
- `exec_run(..., timeout=...)` raises `enroot.errors.TimeoutError` on timeout.
- `exec_run(..., mem_limit=...)` requires `prlimit` on the host.
