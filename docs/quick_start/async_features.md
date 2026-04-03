# Asynchronous Features

This page focuses on coroutine-based container operations.

## 1) Async create -> start -> exec -> kill

```python
import asyncio
from enroot import from_env


async def main():
    client = from_env()
    img = client.images.pull("alpine", "latest")

    container = await client.containers.create_async(
        image=img.tags[0],
        name="demo-async",
        command="sleep 600",
        timeout=120,
    )

    await container.start_async(
        environment={"ASYNC_MODE": "1"},
        mem_limit="512m",
        timeout=30,
    )

    result = await container.exec_run_async(
        "sh -lc 'echo async-ok && echo $ASYNC_MODE'",
        environment={"ASYNC_MODE": "1"},
    )
    print(result.exit_code, result.output.decode("utf-8", errors="replace"))

    await container.kill_async(timeout=5)


asyncio.run(main())
```

## 2) Async timeout on `exec_run_async`

```python
import asyncio
from enroot import from_env, errors


async def main():
    client = from_env()
    c = client.containers.run("alpine", command="sleep 600", detach=True, name="demo-async-timeout")
    try:
        await c.exec_run_async("sh -lc 'sleep 5; echo late'", timeout=1)
    except errors.TimeoutError:
        print("Async timeout triggered")
    finally:
        await c.kill_async()


asyncio.run(main())
```

## 3) Refresh state asynchronously

```python
await container.reload_async()
print(container.status)
print(container.pids)
```

## Notes

- Async methods mirror sync behavior but avoid blocking the event loop.
- `start_async(..., timeout=...)` and `exec_run_async(..., timeout=...)` raise
  `enroot.errors.TimeoutError` when deadlines are exceeded.
