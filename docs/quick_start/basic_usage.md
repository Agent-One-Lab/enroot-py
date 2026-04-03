# Quick Start

This section shows the intended flow:

1. Pull an image
2. Create a container
3. Start the container
4. Run commands inside the container with `exec_run`

## Example

```python
from enroot import from_env

client = from_env()

img = client.images.pull("alpine", "latest")
cont = client.containers.create(img.tags[0], name=None, command="sleep 3600")

cont.start()

res = cont.exec_run("echo hello")
print(res.exit_code, res.output.decode("utf-8", errors="replace"))

cont.kill()
```

## Notes

- `containers.create(...)` accepts some docker-compat arguments, but resource
  limits are not enforced during create. Set limits on `start(...)`/`run(...)`.
- `exec_run` runs `enroot exec` on the container's in-container PID.
- `timeout=...` wraps the host command line with the `timeout` utility so the whole process tree is signaled.

