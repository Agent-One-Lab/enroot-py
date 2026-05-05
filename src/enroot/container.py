from typing import List, Dict, Any, TYPE_CHECKING, Union, BinaryIO, Tuple
import asyncio
import builtins
from .utils import (
    run_enroot,
    run_enroot_async,
    list_containers_fancy,
    list_containers_fancy_async,
    list_containers_plain,
    list_containers_plain_async,
    systemd_prefix,
    random_name,
    allocate_free_port,
    mem_limit_to_bytes,
    _host_argv_with_timeout,
)
if TYPE_CHECKING:
    from .client import EnrootClient
import os
import re
import shutil
from .image import pull_image
import shlex
import subprocess
import time
from dataclasses import dataclass
from .config import ENROOT_DEBUG
from . import errors
import logging

logger = logging.getLogger(__name__)


# SIGABRT (6), SIGBUS (7), SIGSEGV (11) — plausible RLIMIT_AS / allocator crashes, not SIGTERM etc.
_MEMORY_RELATED_SIGNALS = frozenset((6, 7, 11))


def _host_exit_suggests_memory_related_signal(rc: int) -> bool:
    """True only for memory-ish signal deaths, not SIGPIPE/SIGTERM/SIGHUP (141/143/129, …)."""
    if rc < 0:
        return -rc in _MEMORY_RELATED_SIGNALS
    if rc >= 128:
        return (rc - 128) in _MEMORY_RELATED_SIGNALS
    return False


# Tight regexes: avoid matching incidental text (e.g. “not out of memory”) or random “enomem” paths.
_OUTPUT_MEMORY_PATTERNS = (
    # Python traceback line
    re.compile(rb"(?im)^\s*MemoryError\s*:"),
    re.compile(rb"\bstd::bad_alloc\b"),
    re.compile(rb"(?i)\bbad allocation\b"),
    # libc / Perl often emit these at line start
    re.compile(rb"(?im)^\s*out of memory[!.\s]"),
    re.compile(rb"(?i)\bcannot allocate memory\b"),
    re.compile(rb"(?im)^\s*segmentation fault\s*$"),
    re.compile(rb"(?i)\berrno\s*=\s*enomem\b"),
)


def _output_suggests_memory_resource_exhaustion(out_b: bytes, err_b: bytes) -> bool:
    if not out_b and not err_b:
        return False
    blob = out_b + b"\n" + err_b
    return any(p.search(blob) for p in _OUTPUT_MEMORY_PATTERNS)


def _should_raise_prlimit_memory_error(rc: int, out_b: bytes, err_b: bytes) -> bool:
    if rc in (0, 124, 137, 139):
        return False
    return _host_exit_suggests_memory_related_signal(rc) or _output_suggests_memory_resource_exhaustion(
        out_b, err_b
    )


@dataclass
class ExecResult:
    """
    Result of exec_run. Aligned with docker-py: (exit_code, output).
    output is bytes (stdout+stderr combined), or when demux=True a tuple (stdout_bytes, stderr_bytes).
    Tuple-like so (exit_code, output) = container.exec_run(...) works.
    """
    exit_code: int
    output: Union[bytes, tuple[bytes, bytes]]

    def __iter__(self):
        return iter((self.exit_code, self.output))

    def __getitem__(self, index: int):
        return (self.exit_code, self.output)[index]

    def __len__(self) -> int:
        return 2

class Container:
    """Represents a single Enroot container.

    This wrapper provides a docker-py–style API (for example, :meth:`start`,
    :meth:`exec_run`, :meth:`reload`) on top of the ``enroot`` CLI. A container
    is identified by its name, which Enroot also uses as the container ID.
    """
    # Class-wide cache to reduce repeated `enroot list` pressure.
    # Keyed by container name (enroot uses name as container id).
    _PID_CACHE: Dict[str, List[int]] = {}

    def __init__(self, cli: "EnrootClient", name: str,
                 port_map: Dict[str, str], process=None,
                 _created_only: bool = False, _image_id: str | None = None,
                 _start_command=None):
        self._cli = cli
        self.name = name
        self._port_map = port_map
        self._attrs: Dict[str, Any] = {}
        self.pids: List[int] = []
        self._process = process
        self._image_id = _image_id
        self._start_command = _start_command
        self._created_only = _created_only
        if _created_only:
            self._status = "created"
            self._attrs = {
                "NetworkSettings": {"Ports": {}},
                "State": {"Status": "created", "Running": False},
            }
            if _image_id:
                self._attrs["Image"] = _image_id
        else:
            self._created_only = False
            self.reload()

    def _meta(self):
        cached = self._PID_CACHE.get(self.name)
        if cached is not None:
            return {"pids": list(cached)}

        # Use fast plain list first; only call slow list --fancy when container is present
        if self.name not in list_containers_plain():
            self._PID_CACHE.pop(self.name, None)
            return {}
        meta = list_containers_fancy().get(self.name, {})
        pids = meta.get("pids", []) or []
        if pids:
            self._PID_CACHE[self.name] = list(pids)
        else:
            self._PID_CACHE.pop(self.name, None)
        return meta

    async def _meta_async(self):
        """Async variant of _meta() using async list helpers."""
        names = await list_containers_plain_async()
        if self.name not in names:
            return {}
        return (
            await list_containers_fancy_async()
        ).get(self.name, {})

    @property
    def id(self) -> str:
        """Container id (enroot uses name as id)."""
        return self.name

    @property
    def short_id(self) -> str:
        """Short container id (first 12 chars)."""
        return self.id[:12]

    @property
    def client(self) -> "EnrootClient":
        """Docker-compat: container.client for api access."""
        return self._cli

    def stop(self, timeout: int = 10, **_):
        """Stop the container.

        Sends SIGTERM to the tracked start process (if any), waits up to ``timeout``
        seconds, then forcefully kills and removes the container if it is still
        running. Mirrors docker-py ``Container.stop`` semantics as closely as
        possible.

        Args:
            timeout: Maximum number of seconds to wait for a graceful stop.
        """
        if self._process is None:
            if not self.pids:
                self.reload()
            if not self.pids:
                return
            run_enroot(["remove", "--force", self.name], capture=False)
            self._status = "exited"
            return
        try:
            self._process.terminate()
            self._process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait()
        except ProcessLookupError:
            pass
        finally:
            self._process = None
        run_enroot(["remove", "--force", self.name], capture=False)
        self._PID_CACHE.pop(self.name, None)
        self._status = "exited"

    def reload(self):
        """Refresh this container's state from ``enroot list``.

        This updates cached PIDs, status, and docker-py–like metadata such as
        ``attrs["State"]`` and ``attrs["NetworkSettings"]``.
        """
        meta = self._meta()
        self.pids = meta.get("pids", [])
        if self.pids:
            self._PID_CACHE[self.name] = list(self.pids)
        else:
            self._PID_CACHE.pop(self.name, None)
        running = bool(self.pids) or bool(meta)
        # Preserve "created" when container was never started (not in list).
        if not meta and self._attrs.get("State", {}).get("Status") == "created":
            self._status = "created"
            self._attrs.setdefault("State", {})["Running"] = False
            return
        self._status = "running" if running else "exited"
        if "NetworkSettings" not in self._attrs:
            self._attrs["NetworkSettings"] = {"Ports": {}}
        self._attrs["NetworkSettings"]["Ports"] = {
            c: [{"HostIp": "127.0.0.1", "HostPort": h}]
            for c, h in self._port_map.items()
        }
        if "State" not in self._attrs:
            self._attrs["State"] = {}
        self._attrs["State"]["Status"] = self._status
        self._attrs["State"]["Running"] = running

    def put_archive(self, path: str, data: Union[bytes, BinaryIO]) -> bool:
        """Insert a file or directory into the container from a tar archive.

        Args:
            path: Path inside the container where the archive will be extracted
                (must already exist).
            data: Tar archive as bytes or a file-like object.

        Returns:
            True if the operation succeeds.

        Raises:
            errors.APIError: If the container is not running, the operation times
                out, or ``tar`` exits with a non-zero status.
        """
        if not self.pids:
            self.reload()
        if not self.pids:
            raise errors.APIError("Container is not running")
        ident = str(self.pids[0])
        exec_cmd = ["enroot", "exec", ident, "tar", "-C", path, "-xf", "-"]
        proc = subprocess.Popen(
            exec_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            if isinstance(data, bytes):
                stdout, stderr = proc.communicate(input=data, timeout=300)
            else:
                stdout, stderr = proc.communicate(input=data.read(), timeout=300)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            raise errors.APIError("put_archive timed out")
        if proc.returncode != 0:
            raise errors.APIError(f"put_archive failed: {stderr.decode()}")
        return True

    def copy_to(self, local_path: str, container_path: str):
        """Copy a local file or directory into the running container.

        Builds a tar archive on the host and forwards it to :meth:`put_archive`.

        Args:
            local_path: Path to the local file or directory.
            container_path: Destination path inside the container.
        """
        local_path = os.path.abspath(local_path)
        if os.path.isdir(local_path):
            tar_cmd = ["tar", "-C", local_path, "-cf", "-", "."]
        else:
            tar_cmd = ["tar", "-C", os.path.dirname(local_path), "-cf", "-", os.path.basename(local_path)]
        p = subprocess.run(tar_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        self.put_archive(container_path, p.stdout)


    def kill(self, **_):
        """Forcefully stop and remove this container.

        This is intended to mirror docker-py ``Container.kill`` semantics:
        terminate the local start process (if tracked) and then remove the
        container via ``enroot remove --force``.
        """
        # Stop the "enroot start" process first so remove can succeed.
        if self._process is not None:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                pass
            finally:
                self._process = None
        run_enroot(["remove", "--force", self.name], capture=False)
        self._PID_CACHE.pop(self.name, None)
        self._status = "exited"

    def remove(self, force: bool = False, **_):
        """Remove this container via ``enroot remove``.

        Args:
            force: If True, passes ``--force`` to ``enroot remove``.
        """
        cmd = ["remove", self.name]
        if force:
            cmd.insert(1, "--force")
        run_enroot(cmd, capture=False)
        self._PID_CACHE.pop(self.name, None)
        self._status = "exited"

    def start(self, command=None, environment=None,
              mount=None,
              cpu_count: float | None = None,
              mem_limit: str | int | None = None,
              cpus: float | None = None,
              timeout: int = 30,
              **_):
        """Start this container.

        This is similar to ``docker start`` and should be used after
        :meth:`Containers.create`.

        Args:
            command: Optional override command to run instead of the image default.
            environment: Optional mapping of environment variables to inject.
            mount: Optional mapping of host paths to mount options.
            cpu_count: Optional CPU limit used when constructing the systemd unit.
            mem_limit: Optional memory limit (bytes or human-readable string).
            cpus: Docker-py style synonym for ``cpu_count``.
            timeout: Maximum number of seconds to wait for the container to appear
                in ``enroot list``.

        Raises:
            errors.APIError: If ``enroot start`` exits with a non-zero status.
            errors.TimeoutError: If the container does not appear in
                ``enroot list`` before ``timeout`` expires.
        """
        command = command if command is not None else getattr(self, "_start_command", None)
        env_options = []
        environment = environment or {}
        for key, value in environment.items():
            env_options.extend(["--env", f"{key}={value}"])
        if self._port_map:
            host_port = next(iter(self._port_map.values()))
            env_options.extend(["--env", f"PORT={host_port}"])
        mount_options = []
        mount = mount or {}
        for path, options in mount.items():
            mount_options.extend(["--mount", f"{path}:{options}"])
        prefix = systemd_prefix(
            cpu_count if cpu_count is not None else cpus,
            mem_limit,
        )
        start_cmd = [*prefix, "enroot", "start", "--rw", *env_options, *mount_options, self.name]
        if command:
            start_cmd += shlex.split(command) if isinstance(command, str) else list(command)
        process = subprocess.Popen(
            start_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL if not ENROOT_DEBUG else subprocess.PIPE,
            stderr=subprocess.DEVNULL if not ENROOT_DEBUG else subprocess.PIPE,
            start_new_session=True,
            text=True,
        )
        deadline = time.time() + timeout
        while time.time() < deadline:
            polled = process.poll()
            if polled is not None:
                if process.returncode != 0:
                    raise errors.APIError(
                        f"Container '{self.name}' failed to start (exit {process.returncode})."
                    )
                # start command completed cleanly; for short-lived commands the container may
                # never appear in `enroot list` by the time we poll. Treat as successful start.
                self._process = None
                self._created_only = False
                self.reload()
                return
            names = list_containers_plain()
            if self.name in names:
                meta = list_containers_fancy().get(self.name, {})
                if meta.get("pids"):
                    self._process = process
                    self._created_only = False
                    self.reload()
                    return
            time.sleep(0.1)
        if process.poll() is not None and process.returncode != 0:
            raise errors.APIError(
                f"Container '{self.name}' failed to start (exit {process.returncode})."
            )
        if process.poll() is not None and process.returncode == 0:
            self._process = None
            self._created_only = False
            self.reload()
            return
        raise errors.TimeoutError(
            f"Container '{self.name}' did not appear in 'enroot list' within {timeout}s."
        )

    def exec_run(
        self,
        cmd: str | List[str],
        stdout: bool = True,
        stderr: bool = True,
        demux: bool = False,
        workdir: str | None = None,
        user: str | None = None,
        environment: dict | None = None,
        detach: bool = False,
        mem_limit: str | int | None = None,
        mem_guard_limit: str | int | None = None,
        mem_guard_poll_interval: float = 1.0,
        timeout: float | None = None,
        **_,
    ) -> ExecResult:
        """
        Run a command inside this container. Aligned with docker-py exec_run.
        workdir and environment are applied via a shell wrapper (sh -c).
        user= is accepted for API compatibility but has no effect.
        When detach=True, starts the command and returns immediately without waiting.
        Returns (exit_code, output) where output is bytes, or (stdout_bytes, stderr_bytes) when demux=True.

        mem_limit, if set, runs ``prlimit --as=…`` on the host (before ``enroot exec``) so the limit
        applies to the whole ``enroot exec`` process (RLIMIT_AS).
        Accepts int bytes or strings like ``512m``, ``1g`` (see mem_limit_to_bytes).
        Requires ``prlimit`` (util-linux) in PATH on the host.

        mem_guard_limit, if set, wraps the host command (after any ``prlimit`` / ``timeout`` shell) and
        monitors the **total RSS** of the spawned process tree via ``psutil``. If the running
        workload exceeds the RSS cap, the tree is killed and raises :class:`errors.MemGuardError`
        (host exit 137). Requires ``psutil``.

        Invalid arguments or missing host tools (``prlimit``, ``psutil``) raise :class:`errors.APIError`.
        After the command runs, classification is in this order: host exit **124** → built-in
        :exc:`TimeoutError`; **137** when ``mem_guard_limit`` is set → :class:`errors.MemGuardError`
        (RSS cap); else if ``mem_limit`` applied a positive ``prlimit --as`` and the outcome looks
        like an address-space / allocation failure (host exit **134**/**135**/**139** from
        SIGABRT/SIGBUS/SIGSEGV, matching negative subprocess return codes, or stdout/stderr matching
        a small set of allocator / traceback patterns) →
        :class:`errors.MemoryError`. Ordinary tool failures (e.g. ``grep`` exit **1**) return
        :class:`ExecResult` with that exit code. You can set **both** ``mem_limit`` and
        ``mem_guard_limit``: plausible RLIMIT failures surface as ``MemoryError``, RSS kills as
        ``MemGuardError``.

        timeout, if set (seconds), wraps the full host ``enroot exec`` command line with the shell
        ``timeout`` utility. Ignored when ``detach=True``.

        Reload (list/fancy) is only run when pids are not already cached, so repeated exec_run
        calls avoid extra list overhead. If the container was restarted outside this client,
        call container.reload() before exec_run to refresh the PID.
        """
        if user is not None:
            logger.warning(f"Enroot Container: user= is accepted for API compatibility but has no effect: {user}")
        if not self.pids:
            self.reload()
        if not self.pids:
            raise errors.APIError("Container is not running")
        ident = str(self.pids[0])
        if isinstance(cmd, str):
            cmd = shlex.split(cmd)
        if workdir or environment:
            parts = []
            if environment:
                for k, v in environment.items():
                    parts.append(f"export {k}={shlex.quote(str(v))}")
            if workdir:
                parts.append(f"cd {shlex.quote(workdir)}")
            run_cmd = " ".join(shlex.quote(c) for c in cmd)
            shell_cmd = (" && ".join(parts) + " && " + run_cmd) if parts else run_cmd
            cmd = ["sh", "-c", shell_cmd]
        exec_cmd = ["enroot", "exec", ident, *cmd]
        prlimit_as_bytes: int | None = None
        if mem_limit is not None:
            try:
                prlimit_as_bytes = mem_limit_to_bytes(mem_limit)
            except ValueError as e:
                raise errors.APIError(str(e)) from e
            if prlimit_as_bytes and prlimit_as_bytes > 0:
                if shutil.which("prlimit") is None:
                    raise errors.APIError(
                        "mem_limit requires prlimit in PATH (util-linux)"
                    )
                exec_cmd = ["prlimit", f"--as={prlimit_as_bytes}", "--", *exec_cmd]
        if timeout is not None and not detach:
            exec_cmd = _host_argv_with_timeout(exec_cmd, timeout)
        elif timeout is not None and detach:
            logger.warning("exec_run: timeout= is ignored when detach=True")
        if mem_guard_limit is not None and detach:
            logger.warning("exec_run: mem_guard_limit= is ignored when detach=True")
        if detach:
            subprocess.Popen(
                exec_cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return ExecResult(exit_code=0, output=b"")

        if mem_guard_limit is not None:
            try:
                from .utils.mem_guard import run_guarded_capture
            except ImportError as e:
                raise errors.APIError(
                    "mem_guard_limit requires psutil; pip install psutil"
                ) from e
            try:
                mg_bytes = mem_limit_to_bytes(mem_guard_limit)
            except ValueError as e:
                raise errors.APIError(str(e)) from e
            if mg_bytes <= 0:
                raise errors.APIError("mem_guard_limit must be a positive size")
            rc, out_b, err_b = run_guarded_capture(
                exec_cmd,
                mem_limit=mg_bytes,
                poll_interval=float(mem_guard_poll_interval),
                grace_kills=True,
                capture_stdout=stdout,
                capture_stderr=stderr,
            )
        else:
            proc = subprocess.run(
                exec_cmd,
                stdout=subprocess.PIPE if stdout else subprocess.DEVNULL,
                stderr=subprocess.PIPE if stderr else subprocess.DEVNULL,
            )
            out_b = proc.stdout or b""
            err_b = proc.stderr or b""
            rc = proc.returncode if proc.returncode is not None else 0

        if timeout is not None and rc == 124:
            raise errors.TimeoutError(f"exec_run timed out after {timeout}s")
        if mem_guard_limit is not None and rc == 137:
            combined = out_b + (b"\n" if out_b and err_b else b"") + err_b
            raise errors.MemGuardError(
                "exec_run exceeded mem_guard_limit (RSS); process tree was killed",
                exit_code=137,
                output=combined,
                stdout=out_b,
                stderr=err_b,
            )
        if (
            prlimit_as_bytes is not None
            and prlimit_as_bytes > 0
            and _should_raise_prlimit_memory_error(rc, out_b, err_b)
        ):
            detail = err_b.decode("utf-8", errors="replace").strip() or "(no stderr)"
            raise errors.MemoryError(
                f"prlimit-wrapped exec failed (exit {rc}): {detail[:2000]}",
                exit_code=rc,
                stderr=err_b,
            )

        if demux:
            output = (out_b, err_b)
        else:
            output = out_b + (b"\n" if out_b and err_b else b"") + err_b
        return ExecResult(exit_code=rc, output=output)

    async def reload_async(self):
        """Async variant of reload() that avoids blocking list calls."""
        meta = await self._meta_async()
        self.pids = meta.get("pids", [])
        if self.pids:
            self._PID_CACHE[self.name] = list(self.pids)
        else:
            self._PID_CACHE.pop(self.name, None)
        running = bool(self.pids) or bool(meta)
        if not meta and self._attrs.get("State", {}).get("Status") == "created":
            self._status = "created"
            self._attrs.setdefault("State", {})["Running"] = False
            return
        self._status = "running" if running else "exited"
        if "NetworkSettings" not in self._attrs:
            self._attrs["NetworkSettings"] = {"Ports": {}}
        self._attrs["NetworkSettings"]["Ports"] = {
            c: [{"HostIp": "127.0.0.1", "HostPort": h}]
            for c, h in self._port_map.items()
        }
        if "State" not in self._attrs:
            self._attrs["State"] = {}
        self._attrs["State"]["Status"] = self._status
        self._attrs["State"]["Running"] = running

    async def kill_async(self, timeout: int = 10, **_):
        """Asynchronously forcefully stop and remove this container.

        Best-effort async cleanup. The container may have been started via either
        sync :meth:`start` (``subprocess.Popen``) or async :meth:`start_async`
        (``asyncio.subprocess.Process``).

        Args:
            timeout: Maximum number of seconds to wait for the tracked process to
                exit before sending a kill signal.
        """
        if self._process is not None:
            proc = self._process
            try:
                proc.terminate()
            except Exception:
                pass
            loop = asyncio.get_running_loop()
            try:
                if isinstance(proc, asyncio.subprocess.Process):
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=timeout)
                    except asyncio.TimeoutError:
                        try:
                            proc.kill()
                        except Exception:
                            pass
                        await proc.wait()
                else:
                    # subprocess.Popen.wait(timeout=...) blocks in a worker thread.
                    try:
                        await loop.run_in_executor(None, proc.wait, timeout)
                    except subprocess.TimeoutExpired:
                        try:
                            proc.kill()
                        except Exception:
                            pass
                        await loop.run_in_executor(None, proc.wait)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                pass
            finally:
                self._process = None

        # Best-effort removal (mirrors kill() semantics).
        await run_enroot_async(
            ["remove", "--force", self.name],
            capture=False,
            check=False,
        )
        self._PID_CACHE.pop(self.name, None)
        self._status = "exited"

    async def start_async(
        self,
        command=None,
        environment=None,
        mount=None,
        cpu_count: float | None = None,
        mem_limit: str | int | None = None,
        cpus: float | None = None,
        timeout: int = 30,
        **_,
    ):
        """Asynchronously start this container.

        Non-blocking polling variant of :meth:`start` with equivalent semantics.

        Args:
            command: Optional override command to run instead of the image default.
            environment: Optional mapping of environment variables to inject.
            mount: Optional mapping of host paths to mount options.
            cpu_count: Optional CPU limit used when constructing the systemd unit.
            mem_limit: Optional memory limit (bytes or human-readable string).
            cpus: Docker-py style synonym for ``cpu_count``.
            timeout: Maximum number of seconds to wait for the container to appear
                in ``enroot list``.

        Raises:
            errors.APIError: If ``enroot start`` exits with a non-zero status.
            errors.TimeoutError: If the container does not appear in
                ``enroot list`` before ``timeout`` expires.
        """
        command = command if command is not None else getattr(self, "_start_command", None)
        env_options = []
        environment = environment or {}
        for key, value in environment.items():
            env_options.extend(["--env", f"{key}={value}"])
        if self._port_map:
            host_port = next(iter(self._port_map.values()))
            env_options.extend(["--env", f"PORT={host_port}"])
        mount_options = []
        mount = mount or {}
        for path, options in mount.items():
            mount_options.extend(["--mount", f"{path}:{options}"])
        prefix = systemd_prefix(
            cpu_count if cpu_count is not None else cpus,
            mem_limit,
        )
        start_cmd = [*prefix, "enroot", "start", "--rw", *env_options, *mount_options, self.name]
        if command:
            start_cmd += shlex.split(command) if isinstance(command, str) else list(command)

        process = await asyncio.create_subprocess_exec(
            *start_cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL if not ENROOT_DEBUG else asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL if not ENROOT_DEBUG else asyncio.subprocess.PIPE,
            start_new_session=True,
        )

        deadline = time.time() + timeout
        try:
            while time.time() < deadline:
                if process.returncode is not None:
                    if process.returncode != 0:
                        raise errors.APIError(
                            f"Container '{self.name}' failed to start (exit {process.returncode})."
                        )
                    self._process = None
                    self._created_only = False
                    await self.reload_async()
                    return

                names = await list_containers_plain_async()
                if self.name in names:
                    meta = (
                        await list_containers_fancy_async()
                    ).get(self.name, {})
                    if meta.get("pids"):
                        self._process = process
                        self._created_only = False
                        await self.reload_async()
                        return
                await asyncio.sleep(0.1)

            if process.returncode is not None and process.returncode != 0:
                raise errors.APIError(
                    f"Container '{self.name}' failed to start (exit {process.returncode})."
                )
            if process.returncode is not None and process.returncode == 0:
                self._process = None
                self._created_only = False
                await self.reload_async()
                return
            raise errors.TimeoutError(
                f"Container '{self.name}' did not appear in 'enroot list' within {timeout}s."
            )
        except asyncio.CancelledError:
            try:
                process.kill()
            except Exception:
                pass
            try:
                await process.wait()
            except Exception:
                pass
            self._process = None
            raise

    async def exec_run_async(
        self,
        cmd: str | List[str],
        stdout: bool = True,
        stderr: bool = True,
        demux: bool = False,
        workdir: str | None = None,
        user: str | None = None,
        environment: dict | None = None,
        detach: bool = False,
        mem_limit: str | int | None = None,
        mem_guard_limit: str | int | None = None,
        mem_guard_poll_interval: float = 1.0,
        timeout: float | None = None,
        **_,
    ) -> ExecResult:
        """Async version of :meth:`exec_run` (including ``mem_guard_limit``)."""
        if user is not None:
            logger.warning(
                f"Enroot Container: user= is accepted for API compatibility but has no effect: {user}"
            )
        if not self.pids:
            await self.reload_async()
        if not self.pids:
            raise errors.APIError("Container is not running")

        ident = str(self.pids[0])
        if isinstance(cmd, str):
            cmd = shlex.split(cmd)
        if workdir or environment:
            parts = []
            if environment:
                for k, v in environment.items():
                    parts.append(f"export {k}={shlex.quote(str(v))}")
            if workdir:
                parts.append(f"cd {shlex.quote(workdir)}")
            run_cmd = " ".join(shlex.quote(c) for c in cmd)
            shell_cmd = (" && ".join(parts) + " && " + run_cmd) if parts else run_cmd
            cmd = ["sh", "-c", shell_cmd]

        exec_cmd = ["enroot", "exec", ident, *cmd]
        prlimit_as_bytes: int | None = None
        if mem_limit is not None:
            try:
                prlimit_as_bytes = mem_limit_to_bytes(mem_limit)
            except ValueError as e:
                raise errors.APIError(str(e)) from e
            if prlimit_as_bytes and prlimit_as_bytes > 0:
                if shutil.which("prlimit") is None:
                    raise errors.APIError(
                        "mem_limit requires prlimit in PATH (util-linux)"
                    )
                exec_cmd = ["prlimit", f"--as={prlimit_as_bytes}", "--", *exec_cmd]

        if timeout is not None and not detach:
            exec_cmd = _host_argv_with_timeout(exec_cmd, timeout)
        elif timeout is not None and detach:
            logger.warning("exec_run: timeout= is ignored when detach=True")
        if mem_guard_limit is not None and detach:
            logger.warning("exec_run_async: mem_guard_limit= is ignored when detach=True")

        if detach:
            proc = await asyncio.create_subprocess_exec(
                *exec_cmd,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            _ = proc
            return ExecResult(exit_code=0, output=b"")

        if mem_guard_limit is not None:
            try:
                from .utils.mem_guard import MemGuard
            except ImportError as e:
                raise errors.APIError(
                    "mem_guard_limit requires psutil; pip install psutil"
                ) from e
            try:
                mg_bytes = mem_limit_to_bytes(mem_guard_limit)
            except ValueError as e:
                raise errors.APIError(str(e)) from e
            if mg_bytes <= 0:
                raise errors.APIError("mem_guard_limit must be a positive size")
            guard = MemGuard(
                mem_limit_bytes=mg_bytes,
                poll_interval=float(mem_guard_poll_interval),
            )
            stdout_opt = asyncio.subprocess.PIPE if stdout else asyncio.subprocess.DEVNULL
            stderr_opt = asyncio.subprocess.PIPE if stderr else asyncio.subprocess.DEVNULL
            rc, out_b, err_b = await guard.run_capture(
                exec_cmd,
                stdout=stdout_opt,
                stderr=stderr_opt,
            )
        else:
            stdout_opt = asyncio.subprocess.PIPE if stdout else asyncio.subprocess.DEVNULL
            stderr_opt = asyncio.subprocess.PIPE if stderr else asyncio.subprocess.DEVNULL
            proc = await asyncio.create_subprocess_exec(
                *exec_cmd,
                stdout=stdout_opt,
                stderr=stderr_opt,
            )
            try:
                out_b, err_b = await proc.communicate()
            except asyncio.CancelledError:
                proc.kill()
                await proc.wait()
                raise

            out_b = out_b or b""
            err_b = err_b or b""
            rc = proc.returncode if proc.returncode is not None else 0

        if timeout is not None and rc == 124:
            raise errors.TimeoutError(f"Command timed out after {timeout}s")
        if mem_guard_limit is not None and rc == 137:
            combined = out_b + (b"\n" if out_b and err_b else b"") + err_b
            raise errors.MemGuardError(
                "Command exceeded mem_guard_limit (RSS); process tree was killed",
                exit_code=137,
                output=combined,
                stdout=out_b,
                stderr=err_b,
            )
        if (
            prlimit_as_bytes is not None
            and prlimit_as_bytes > 0
            and _should_raise_prlimit_memory_error(rc, out_b, err_b)
        ):
            detail = err_b.decode("utf-8", errors="replace").strip() or "(no stderr)"
            raise errors.MemoryError(
                f"Command failed (exit {rc}): {detail[:2000]}",
                exit_code=rc,
                stderr=err_b,
            )

        if demux:
            output = (out_b, err_b)
        else:
            output = out_b + (b"\n" if out_b and err_b else b"") + err_b
        return ExecResult(exit_code=rc, output=output)

    def logs(self, **_) -> bytes:
        """Return container logs (not implemented; returns ``b''``)."""
        return b""

    @property
    def status(self):
        if getattr(self, "_created_only", False):
            return "created"
        if not self.pids:
            self.reload()
        return self._status

    @property
    def attrs(self):
        return self._attrs


class Containers:
    """Container collection helper exposed as ``client.containers``."""

    def __init__(self, cli: "EnrootClient"):
        """Collection helper exposed as ``client.containers``.

        This is the main entry point for creating, listing and looking up containers.
        """
        self._cli = cli

    def run(self, image, command=None, name=None, timeout=120, detach=False,
            remove=False, ports=None, mount=None, environment=None,
            cpu_count: float | None = None, mem_limit: str | int | None = None,
            cpus: float | None = None,  # docker-py synonym
            **_):
        """Create and start a container in detach mode.

        This is a convenience wrapper for creating an Enroot container, launching
        it, and returning a :class:`Container` object.

        Args:
            image: Image reference (string or :class:`Image`).
            command: Optional command to run inside the container.
            name: Optional explicit container name; otherwise a random name is used.
            timeout: Maximum number of seconds to wait for the container to appear
                in ``enroot list``.
            detach: Must be ``True``; non-detach mode is not implemented.
            remove: Currently ignored; present for docker-py compatibility.
            ports: Optional port mappings in docker-py style (for example, ``{"8080/tcp": 8080}``).
            mount: Optional mount specification mapping host paths to options.
            environment: Optional dict of environment variables.
            cpu_count: Optional CPU limit for the systemd unit.
            mem_limit: Optional memory limit for the systemd unit.
            cpus: Docker-py style synonym for ``cpu_count``.

        Returns:
            A :class:`Container` representing the started container.

        Raises:
            NotImplementedError: If ``detach`` is False.
            errors.APIError: If the container fails to start.
            errors.TimeoutError: If the container does not appear in
                ``enroot list`` before ``timeout`` expires.
        """
        if not detach:
            raise NotImplementedError("detach=False not supported")

        cpu_limit = cpu_count if cpu_count is not None else cpus
        name = name or random_name()

        # Check if a container with this name is running
        if name in list_containers_plain():
            raise errors.APIError(f"A container with name '{name}' is already running.")

        try:
            img = pull_image(image) if isinstance(image, str) else image
        except errors.ImageNotFound:
            raise
        except Exception as e:
            raise errors.APIError(str(e)) from e
        logger.debug("create %s", ["create", "--name", name, img.id])
        try:
            run_enroot(["create", "--name", name, img.id], check=True)
        except RuntimeError as e:
            raise errors.APIError(str(e)) from e

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

        mount_options = []
        mount = mount or {}
        for path, options in mount.items():
            mount_options.extend(["--mount", f"{path}:{options}"])

        # launch
        prefix = systemd_prefix(cpu_limit, mem_limit)

        start_cmd = [*prefix, "enroot", "start", "--rw", *env_options, *mount_options, name]
        if command:
            start_cmd += shlex.split(command) if isinstance(command, str) \
                         else list(command)

        logger.debug("Starting command: %s", " ".join(start_cmd))
        process = subprocess.Popen(start_cmd,
                         stdin=subprocess.PIPE,
                         stdout=subprocess.DEVNULL if not ENROOT_DEBUG else subprocess.PIPE,
                         stderr=subprocess.DEVNULL if not ENROOT_DEBUG else subprocess.PIPE,
                         start_new_session=True,
                         text=True)
        # Note: by using a pipe for stdin, we prevent enroot from holding onto
        # the terminal's stdin, which caused issues on exit. The pipe will
        # be closed automatically when this process exits.

        deadline = time.time() + timeout
        while time.time() < deadline:
            polled = process.poll()
            if polled is not None:
                if process.returncode != 0:
                    raise errors.APIError(
                        f"Container '{name}' failed to start (exit {process.returncode})\n"
                        f"stderr: {process.stderr.read().strip() if process.stderr else ''}\n"
                        f"stdout: {process.stdout.read().strip() if process.stdout else ''}"
                    )
                # For short-lived commands (`run(..., detach=True, command='echo hi')`),
                # process may finish before list polling observes a running container.
                c = Container(
                    self._cli,
                    name,
                    port_map,
                    process=None,
                    _image_id=img.id,
                )
                c.reload()
                return c
            names = list_containers_plain()
            if name in names:
                container_info = list_containers_fancy().get(name, {})
                if container_info.get("pids"):
                    return Container(
                        self._cli,
                        name,
                        port_map,
                        process=process,
                        _image_id=img.id,
                    )
            time.sleep(0.5)

        # Container did not appear within deadline
        if process.poll() is not None and process.returncode != 0:
            raise errors.APIError(
                f"Container '{name}' failed to start (exit {process.returncode})."
            )
        if process.poll() is not None and process.returncode == 0:
            c = Container(
                self._cli,
                name,
                port_map,
                process=None,
                _image_id=img.id,
            )
            c.reload()
            return c
        raise errors.TimeoutError(
            f"Container '{name}' did not appear in 'enroot list' within {timeout}s. "
            "Check 'enroot start' or 'enroot list --fancy' output."
        )

    def create(self, image, command=None, name=None, ports=None, mount=None,
               environment=None, cpu_count: float | None = None,
               mem_limit: str | int | None = None, cpus: float | None = None,
               timeout: float | None = 120,
               **_):
        """Create a container without starting it. Similar to docker create.

        ``timeout`` limits how long ``enroot create`` may run in seconds (including under Slurm).
        It is implemented via ``run_enroot`` (see ``enroot.utils``) using the shell ``timeout`` utility so the host
        ``enroot`` / ``srun`` process tree is signaled on expiry (not only a Python subprocess
        timeout). Pass ``None`` for no limit. Raises :class:`errors.TimeoutError` when the limit is exceeded.
        """
        name = name or random_name()
        if name in list_containers_plain():
            raise errors.APIError(f"A container with name '{name}' is already running.")
        try:
            img = pull_image(image) if isinstance(image, str) else image
        except errors.ImageNotFound:
            raise
        except Exception as e:
            raise errors.APIError(str(e)) from e
        try:
            run_enroot(
                ["create", "--name", name, img.id],
                check=True,
                timeout=timeout,
            )
        except errors.TimeoutError:
            raise
        except RuntimeError as e:
            raise errors.APIError(str(e)) from e
        ports = ports or {}
        port_map = {f"{p.split('/')[0]}/tcp": p.split('/')[0] for p in ports}
        if port_map:
            free_port = allocate_free_port()
            for k in port_map:
                port_map[k] = free_port
        return Container(
            self._cli, name, port_map, process=None,
            _created_only=True, _image_id=img.id,
            _start_command=command,
        )

    async def create_async(
        self,
        image,
        command=None,
        name=None,
        ports=None,
        mount=None,
        environment=None,
        cpu_count: float | None = None,
        mem_limit: str | int | None = None,
        cpus: float | None = None,
        timeout: float | None = 120,
        **_,
    ) -> Container:
        """Async version of :meth:`create`."""
        _ = mount, environment, cpu_count, mem_limit, cpus  # create() currently ignores these
        name = name or random_name()
        exists = name in await list_containers_plain_async()
        if exists:
            raise errors.APIError(f"A container with name '{name}' is already running.")

        try:
            img = pull_image(image) if isinstance(image, str) else image
        except errors.ImageNotFound:
            raise
        except Exception as e:
            raise errors.APIError(str(e)) from e

        try:
            await run_enroot_async(
                ["create", "--name", name, img.id],
                check=True,
                timeout=timeout,
            )
        except errors.TimeoutError:
            raise
        except RuntimeError as e:
            raise errors.APIError(str(e)) from e

        ports = ports or {}
        port_map = {f"{p.split('/')[0]}/tcp": p.split('/')[0] for p in ports}
        if port_map:
            free_port = allocate_free_port()
            for k in port_map:
                port_map[k] = free_port

        return Container(
            self._cli,
            name,
            port_map,
            process=None,
            _created_only=True,
            _image_id=img.id,
            _start_command=command,
        )

    def list(
        self,
        **_,
    ) -> List[Container]:
        """List containers known to ``enroot list``.

        Returns:
            A list of :class:`Container` objects for each running container name.
        """
        names = list_containers_plain().keys()
        return [Container(self._cli, nm, {}, process=None) for nm in names]

    def get(
        self,
        ident: str,
    ) -> Container:
        """Fetch a container by name.

        Args:
            ident: Container name (Enroot ID).

        Returns:
            A :class:`Container` for the requested name.

        Raises:
            errors.NotFound: If the container is not present in ``enroot list``.
        """
        if ident not in list_containers_plain():
            raise errors.NotFound(f"Container {ident!r} not found")
        return Container(self._cli, ident, {}, process=None)
