from __future__ import annotations
import subprocess
import uuid
from .container import Containers
from .image import Images
from .utils import run_enroot, parse_list
from . import errors


class _EnrootAPI:
    """Docker-compat API: exec_create, exec_start, exec_inspect, inspect_container for swebench."""

    def __init__(self, client: "EnrootClient"):
        self._client = client
        self._exec_registry: dict[str, tuple[str, str]] = {}

    def exec_create(self, container_id: str, cmd: str) -> dict:
        exec_id = str(uuid.uuid4())
        self._exec_registry[exec_id] = (container_id, cmd)
        return {"Id": exec_id}

    def exec_start(self, exec_id: str, stream: bool = False):
        if exec_id not in self._exec_registry:
            raise errors.NotFound(f"Exec {exec_id!r} not found")
        container_id, cmd = self._exec_registry[exec_id]
        container = self._client.containers.get(container_id)
        container.reload()
        if not container.pids:
            raise errors.APIError("Container is not running")
        ident = str(container.pids[0])
        # Write in-container PID to file so exec_inspect can return it for timeout kill
        safe_id = exec_id.replace("-", "_")
        wrapped = (
            f"( {cmd} ) > /tmp/.exec_stdout_{safe_id} 2>&1 & "
            f"echo $! > /tmp/.exec_pid_{safe_id}; wait; cat /tmp/.exec_stdout_{safe_id}"
        )
        proc = subprocess.Popen(
            ["enroot", "exec", ident, "sh", "-c", wrapped],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if not stream:
            out, err = proc.communicate()
            return out + (b"\n" if err else b"") + (err or b"")
        # Stream: yield chunks until done
        while True:
            chunk = proc.stdout.read(4096)  # type: ignore[union-attr]
            if not chunk:
                break
            yield chunk
        proc.wait()

    def exec_inspect(self, exec_id: str) -> dict:
        if exec_id not in self._exec_registry:
            raise errors.NotFound(f"Exec {exec_id!r} not found")
        container_id, _ = self._exec_registry[exec_id]
        container = self._client.containers.get(container_id)
        container.reload()
        if not container.pids:
            raise errors.APIError("Container is not running")
        ident = str(container.pids[0])
        safe_id = exec_id.replace("-", "_")
        out = run_enroot(
            ["exec", ident, "cat", f"/tmp/.exec_pid_{safe_id}"],
            capture=True,
            check=False,
        )
        pid_str = (out or "").strip() or "0"
        try:
            pid = int(pid_str)
        except ValueError:
            pid = 0
        return {"Pid": pid}

    def inspect_container(self, container_id: str) -> dict:
        container = self._client.containers.get(container_id)
        container.reload()
        # Host PID for forceful kill (swebench fallback when stop() fails)
        pid = 0
        if container.pids:
            pid = container.pids[0]
        elif getattr(container, "_process", None) is not None:
            pid = getattr(container._process, "pid", 0) or 0
        return {"State": {"Pid": pid}}


class EnrootClient:
    def __init__(self):
        self.images = Images(self)
        self.containers = Containers(self)
        self.api = _EnrootAPI(self)

    def ping(self) -> bool:
        try:
            run_enroot(["version"])
            return True
        except Exception as e:
            raise errors.APIError(str(e)) from e

    def close(self):
        pass


def from_env() -> EnrootClient:
    return EnrootClient()
