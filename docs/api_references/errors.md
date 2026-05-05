# Errors

All client errors come from `enroot.errors`.

- `errors.EnrootError`: base class for everything below.
- `errors.APIError`: backend command failed, API precondition failed, or invalid exec arguments / missing tools (e.g. bad `mem_limit`, no `prlimit`, no `psutil` for `mem_guard_limit`).
- `errors.NotFound`: missing container/exec id.
- `errors.ImageNotFound`: missing image.
- `errors.TimeoutError`: any timeout from this library — container `start` / `start_async` polling, `run_enroot` / `run_enroot_async` with `timeout=`, **and** `exec_run` / `exec_run_async` with `timeout=` (host exit **124**). Inherits from `Exception`, not from the built-in `TimeoutError`.
- `errors.MemoryError` *(subclass of `APIError`)*: raised **after** an `exec_run` / `exec_run_async` that applied a positive `prlimit --as` (`mem_limit=`) when the host outcome looks RLIMIT/OOM-shaped — i.e. exit code is **not** in `(0, 124, 137, 139)` **and** either the process died from a memory-related signal (SIGABRT/SIGBUS/SIGSEGV → 134/135/139 or negative subprocess return codes -6/-7/-11) **or** stdout/stderr matches a small set of allocator/traceback patterns (`MemoryError:`, `std::bad_alloc`, `out of memory`, `cannot allocate memory`, `segmentation fault`, `errno=ENOMEM`, …). Ordinary tool failures (e.g. `grep` exit **1**) are returned as a normal `ExecResult`. Carries `exit_code` and `stderr` attributes.
- `errors.MemGuardError` *(subclass of `APIError`)*: raised **after** a guarded run when the RSS cap was exceeded (host exit **137**). Carries `exit_code`, `output`, `stdout`, and `stderr` attributes.

## Catching exec_run timeouts

`exec_run` / `exec_run_async` with `timeout=` raise `enroot.errors.TimeoutError` on host exit 124. This is **not** a subclass of the built-in `TimeoutError`, so `except TimeoutError:` (the built-in name) will not catch it — import the class explicitly:

```python
from enroot import errors

try:
    container.exec_run("sleep 60", timeout=1)
except errors.TimeoutError:
    print("Command timed out")
```
