# API Usage Examples

This page focuses on synchronous APIs and common arguments such as
`mem_limit`, `mem_guard_limit`, `timeout`, and `copy_to`.

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
    # NOTE: enroot.errors.TimeoutError, not the built-in TimeoutError.
    print("Command timed out")
```

## 3) `exec_run` with memory limit (`mem_limit`, prlimit-based)

```python
result = container.exec_run(
    cmd="python - <<'PY'\na=[0]*10_000_000\nprint('ok')\nPY",
    mem_limit="256m",  # applies `prlimit --as` before `enroot exec`
)
print(result.exit_code)
```

## 4) `exec_run` with RSS cap (`mem_guard_limit`, psutil-based)

```python
result = container.exec_run(
    cmd="sh -lc 'python -c \"a=bytearray(2*1024*1024*1024)\"'",
    mem_guard_limit="512m",        # kill the tree if total RSS exceeds 512MiB
    mem_guard_poll_interval=0.5,   # check RSS every 0.5s (default 1.0)
)
print(result.exit_code)
```

## 5) Copy files into container with `copy_to`

```python
# Copy local file/dir into the running container.
container.copy_to(local_path="./configs", container_path="/tmp")

check = container.exec_run("ls -la /tmp")
print(check.output.decode("utf-8", errors="replace"))
```

## 6) Stop and cleanup

```python
container.stop(timeout=5)
container.remove(force=True)
```

To sweep leftovers on the host in one go — e.g. containers a killed job never
removed — filter by a naming prefix so you never touch anyone else's:

```python
from enroot import clear_enroot_containers

removed = clear_enroot_containers(prefix="myapp-")  # None removes every container on the host
```

## Notes

- Resource-limit arguments passed to `containers.create(...)` are compatibility
  arguments for docker-style APIs and do not enforce limits at create time.
  Apply limits when starting/running containers (for example via
  `start(..., mem_limit=..., cpu_count=...)`), which wraps the start under
  `systemd-run` when available.
- `start(..., timeout=...)` waits for the container to appear in `enroot list`,
  raising `enroot.errors.TimeoutError` on expiry.
- `exec_run(..., timeout=...)` raises **`enroot.errors.TimeoutError`** on host
  timeout (exit 124). It is *not* a subclass of the built-in `TimeoutError`,
  so import it from `enroot.errors` to catch it.
- `exec_run(..., mem_limit=...)` requires `prlimit` (util-linux) in `PATH`;
  bad arguments / a missing binary raise `errors.APIError`. After the run,
  only outcomes that look like an address-space / allocation failure
  (memory-related signal death — SIGABRT/SIGBUS/SIGSEGV — or stderr/stdout
  containing allocator/traceback patterns) raise `enroot.errors.MemoryError`.
  Ordinary tool failures (e.g. `grep` exit 1) are returned as a normal
  `ExecResult`.
- `exec_run(..., mem_guard_limit=...)` needs `psutil`; setup issues raise
  `errors.APIError`. When the RSS of the spawned process tree exceeds the cap,
  the tree is killed and `enroot.errors.MemGuardError` is raised (host exit 137).
- You can set `mem_limit` and `mem_guard_limit` together: prlimit-style failures
  surface as `MemoryError`, RSS kills as `MemGuardError`.
