from typing import List, Dict, Any, TYPE_CHECKING
from .utils import run_enroot, parse_list, systemd_prefix, random_name, allocate_free_port
if TYPE_CHECKING:
    from .client import EnrootClient
import shlex
import subprocess
import time
import pathlib
from dataclasses import dataclass
from .config import ENROOT_HOME, ENROOT_DEBUG

@dataclass
class ExecResult:
    exit_code: int
    output: str

class Container:
    def __init__(self, cli: "EnrootClient", name: str,
                 port_map: Dict[str, str], process=None):
        self._cli = cli
        self.name = name
        self._port_map = port_map
        self._attrs: Dict[str, Any] = {}
        self.pids: List[int] = []
        self._process = process
        self.reload()

    def _meta(self):
        return parse_list(run_enroot(["list", "--fancy"])).get(self.name, {})

    def reload(self):
        meta = self._meta()
        self.pids = meta.get("pids", [])
        running = bool(self.pids) or bool(meta)
        self._status = "running" if running else "exited"
        if not self._attrs:
            self._attrs = {
                "NetworkSettings": {
                    "Ports": {c: [{"HostIp": "127.0.0.1",
                                   "HostPort": h}]
                              for c, h in self._port_map.items()}
                },
                "State": {
                    "Status": self._status,
                    "Running": running,
                },
            }

    def kill(self, **_):
        run_enroot(["remove", "--force", self.name], capture=False)
        self._status = "exited"

    def remove(self, force: bool = False, **_):
        run_enroot(["remove", "--force" if force else "", self.name],
                    capture=False)
        self._status = "exited"

    def exec_run(self, cmd: str | List[str], **_) -> ExecResult:
        self.reload()  # Make sure pids are up to date
        ident = str(self.pids[0])

        if isinstance(cmd, str):
            cmd = shlex.split(cmd)
        # Use subprocess directly to capture both stdout and stderr
        proc = subprocess.run(
            ["enroot", "exec", ident, *cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        # Decode both stdout and stderr
        stdout_text = proc.stdout.decode().strip() if proc.stdout else ""
        stderr_text = proc.stderr.decode().strip() if proc.stderr else ""
        # Combine stdout and stderr (stdout first, then stderr if present)
        if stdout_text and stderr_text:
            output = stdout_text + "\n" + stderr_text
        else:
            output = stdout_text or stderr_text
        return ExecResult(exit_code=proc.returncode, output=output)

    def logs(self, **_) -> bytes:
        return b""

    @property
    def status(self):
        self.reload()
        return self._status

    @property
    def attrs(self):
        return self._attrs


class Containers:
    def __init__(self, cli: "EnrootClient"):
        self._cli = cli

    def run(self, image, command=None, name=None, *, detach=False,
            remove=False, ports=None, environment=None,
            cpu_count: float | None = None, mem_limit: str | int | None = None,
            cpus: float | None = None,  # docker-py synonym
            **_):
        if not detach:
            raise NotImplementedError("detach=False not supported")

        cpu_limit = cpu_count if cpu_count is not None else cpus
        name = name or random_name()

        # Check if a container with this name is running
        if name in parse_list(run_enroot(["list"], capture=True)):
            raise RuntimeError(f"A container with name '{name}' is already running.")

        # Try to create the container, handling the case where it already exists (but is stopped)
        try:
            img_path = None
            path = pathlib.Path(str(image))
            if path.suffix == ".sqsh" and path.exists():
                img_path = str(path)
            else:
                img_path = f"{ENROOT_HOME}/images/{str(image).replace('/', '+').replace(':', '+')}.sqsh"
                if not pathlib.Path(img_path).exists():
                    run_enroot(["import", "--output", img_path, f"docker://{image}"], capture=False)
            # Use check=True to raise an error if create fails
            run_enroot(["create", "--name", name, img_path], check=True)
        except RuntimeError as e:
            # Check the error message to see if it's an "already exists" error
            if "already exists" in str(e).lower():
                raise RuntimeError(f"A container with name '{name}' already exists (but is stopped).") from e
            else:
                raise  # Re-raise other creation errors

        # Handle environment variables
        env_options = []
        environment = environment or {}
        for key, value in environment.items():
            env_options.extend(["--env", f"{key}={value}"])

        # Handle port mapping
        ports = ports or {}
        port_map = {f"{p.split('/')[0]}/tcp": p.split('/')[0] for p in ports}
        if port_map:
            free_port = allocate_free_port()
            for port in port_map.keys():
                port_map[port] = free_port
            env_options.extend(["--env", f"PORT={free_port}"])

        # launch
        # TODO: add resource limits
        prefix = systemd_prefix(cpu_limit, mem_limit)

        start_cmd = ["enroot", "start", "--rw", *env_options, name]
        if command:
            start_cmd += shlex.split(command) if isinstance(command, str) \
                         else list(command)
        print(start_cmd)
        process = subprocess.Popen(start_cmd,
                         stdout=subprocess.DEVNULL if not ENROOT_DEBUG else None,
                         stderr=subprocess.DEVNULL if not ENROOT_DEBUG else None,
                         start_new_session=True)

        deadline = time.time() + 15
        while time.time() < deadline:
            container_info = parse_list(run_enroot(["list", "--fancy"])).get(name, {})
            if container_info.get("pids"):
                break
            time.sleep(0.1)

        return Container(self._cli, name, port_map, process=process)

    def list(self, **_) -> List[Container]:
        names = parse_list(run_enroot(["list"])).keys()
        return [Container(self._cli, nm, {}) for nm in names]

    def get(self, ident: str) -> Container:
        if ident not in parse_list(run_enroot(["list"])):
            raise RuntimeError(f"Container {ident!r} not found")
        return Container(self._cli, ident, {})

