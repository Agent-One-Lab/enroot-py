"""
Monitor a process tree's physical memory (RSS) and kill it if the total exceeds a limit.

This complements ``prlimit --as`` (virtual address space): RSS monitoring catches
actual resident usage and can react to workloads that stay below RLIMIT_AS but still
drive the host toward OOM under many concurrent containers.

Usage (CLI):
    python -m enroot.utils.mem_guard --limit 50G -- your_command arg1 arg2

Library: see :func:`run_guarded`, :func:`run_guarded_capture`, and :class:`MemGuard`.

Exit codes:
    137 — Process was killed due to memory limit
    Otherwise — The command's own exit code
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass

try:
    import psutil
except ImportError as _e:  # pragma: no cover - exercised when psutil missing
    psutil = None  # type: ignore[misc, assignment]
    _PSUTIL_IMPORT_ERROR = _e
else:
    _PSUTIL_IMPORT_ERROR = None

log = logging.getLogger("enroot.mem_guard")


def _require_psutil() -> None:
    if psutil is None:
        raise ImportError(
            "mem_guard requires psutil; install with: pip install psutil"
        ) from _PSUTIL_IMPORT_ERROR


def parse_size(s: str) -> int:
    """Parse a human-readable size string like '50G', '512M', '1T' into bytes."""
    s = s.strip().upper()
    multipliers = {
        "K": 1024,
        "KB": 1024,
        "M": 1024**2,
        "MB": 1024**2,
        "G": 1024**3,
        "GB": 1024**3,
        "T": 1024**4,
        "TB": 1024**4,
    }
    for suffix, mult in sorted(multipliers.items(), key=lambda x: -len(x[0])):
        if s.endswith(suffix):
            return int(float(s[: -len(suffix)]) * mult)
    return int(s)


def format_size(b: int) -> str:
    """Format bytes into a human-readable string."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(b) < 1024:
            return f"{b:.1f}{unit}"
        b /= 1024
    return f"{b:.1f}PB"


@dataclass
class ProcessInfo:
    """Snapshot of a single process."""

    pid: int
    name: str
    rss_bytes: int
    cmdline: str


class MemGuard:
    """
    Monitor a subprocess tree's total RSS and kill it if it exceeds the limit.

    Attributes:
        mem_limit_bytes: Maximum total RSS in bytes.
        poll_interval: Seconds between memory checks.
        grace_kills: If True, try SIGTERM first, then SIGKILL after grace_period.
        grace_period: Seconds to wait after SIGTERM before SIGKILL.
        on_kill: Optional async callback invoked when killing (receives list of ProcessInfo).
        peak_rss: Peak RSS observed during the run.
    """

    def __init__(
        self,
        mem_limit_bytes: int,
        poll_interval: float = 1.0,
        grace_kills: bool = True,
        grace_period: float = 5.0,
        on_kill=None,
    ):
        _require_psutil()
        self.mem_limit_bytes = mem_limit_bytes
        self.poll_interval = poll_interval
        self.grace_kills = grace_kills
        self.grace_period = grace_period
        self.on_kill = on_kill
        self.peak_rss: int = 0
        self._process: psutil.Process | None = None

    def _get_tree_info(self) -> list[ProcessInfo]:
        """Get RSS and metadata for the root process and all descendants."""
        if self._process is None:
            return []
        try:
            if not self._process.is_running():
                return []
        except psutil.NoSuchProcess:
            return []

        infos = []
        try:
            procs = [self._process] + self._process.children(recursive=True)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return []

        for p in procs:
            try:
                mem = p.memory_info()
                cmdline = " ".join(p.cmdline()) or p.name()
                infos.append(
                    ProcessInfo(
                        pid=p.pid,
                        name=p.name(),
                        rss_bytes=mem.rss,
                        cmdline=cmdline[:120],
                    )
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return infos

    def _get_total_rss(self) -> tuple[int, list[ProcessInfo]]:
        """Return (total_rss_bytes, list_of_process_infos)."""
        infos = self._get_tree_info()
        total = sum(p.rss_bytes for p in infos)
        return total, infos

    def _kill_tree(self) -> None:
        """Kill the entire process tree."""
        if self._process is None:
            return
        try:
            children = self._process.children(recursive=True)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            children = []

        all_procs = children + [self._process]

        if self.grace_kills:
            for p in all_procs:
                try:
                    p.terminate()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            _, alive = psutil.wait_procs(all_procs, timeout=self.grace_period)

            for p in alive:
                try:
                    p.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        else:
            for p in all_procs:
                try:
                    p.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

    async def _monitor_until_done(self, proc: asyncio.subprocess.Process) -> bool:
        """
        Poll RSS until ``proc`` exits or limit exceeded.

        Returns:
            True if the tree was killed for exceeding the memory limit.
        """
        self._process = psutil.Process(proc.pid)
        log.info(
            "Started PID=%s with RSS memory limit=%s",
            proc.pid,
            format_size(self.mem_limit_bytes),
        )

        killed = False
        try:
            while proc.returncode is None:
                total_rss, infos = self._get_total_rss()
                self.peak_rss = max(self.peak_rss, total_rss)

                if total_rss > self.mem_limit_bytes:
                    log.warning(
                        "MEMORY LIMIT EXCEEDED: %s > %s",
                        format_size(total_rss),
                        format_size(self.mem_limit_bytes),
                    )
                    log.warning("Process tree at time of kill:")
                    for p in sorted(infos, key=lambda x: -x.rss_bytes):
                        log.warning(
                            "  PID=%s  RSS=%s  %s",
                            p.pid,
                            format_size(p.rss_bytes),
                            p.cmdline,
                        )

                    if self.on_kill:
                        await self.on_kill(infos)

                    self._kill_tree()
                    killed = True
                    break

                try:
                    await asyncio.wait_for(proc.wait(), timeout=self.poll_interval)
                except asyncio.TimeoutError:
                    pass
        except asyncio.CancelledError:
            self._kill_tree()
            raise

        if proc.returncode is None:
            try:
                await asyncio.wait_for(proc.wait(), timeout=10)
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                await proc.wait()

        return killed

    async def run(self, cmd: list[str]) -> int:
        """
        Launch cmd as a subprocess, monitor its memory, and return its exit code.
        Returns 137 if killed due to memory limit. Stdio is inherited.
        """
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=None,
            stderr=None,
        )
        killed = await self._monitor_until_done(proc)
        exit_code = 137 if killed else (proc.returncode or 0)
        log.info(
            "Process exited with code %s (peak RSS=%s)",
            exit_code,
            format_size(self.peak_rss),
        )
        return exit_code

    async def run_capture(
        self,
        cmd: list[str],
        *,
        stdin: int | None = None,
        stdout: int = asyncio.subprocess.PIPE,
        stderr: int = asyncio.subprocess.PIPE,
    ) -> tuple[int, bytes, bytes]:
        """
        Like :meth:`run`, but capture stdout/stderr (like ``subprocess.run(..., capture_output=True)``).

        Pass ``asyncio.subprocess.DEVNULL`` for ``stdout`` or ``stderr`` to discard that stream.

        Large outputs can fill pipe buffers; use inherited stdio via :meth:`run` if that is a concern.
        """
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=stdin if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
        )
        killed = await self._monitor_until_done(proc)
        out_b, err_b = await proc.communicate()
        out_b = out_b or b""
        err_b = err_b or b""
        rc = 137 if killed else (proc.returncode if proc.returncode is not None else 0)
        log.info(
            "Process exited with code %s (peak RSS=%s)",
            rc,
            format_size(self.peak_rss),
        )
        return rc, out_b, err_b

    async def run_shell(self, command: str) -> int:
        """Run a shell command string under monitoring (stdio inherited)."""
        return await self.run(["bash", "-c", command])


def run_guarded(
    cmd: list[str] | str,
    mem_limit: str | int,
    poll_interval: float = 1.0,
    grace_kills: bool = True,
) -> int:
    """
    Synchronous wrapper. Can be called from non-async code.

    Args:
        cmd: Command as a list or shell string.
        mem_limit: e.g. ``\"50G\"``, ``\"512M\"``, or integer bytes.
        poll_interval: Seconds between checks.
        grace_kills: Try SIGTERM before SIGKILL.

    Returns:
        Exit code (137 if killed for memory).
    """
    _require_psutil()
    if isinstance(mem_limit, str):
        mem_limit_i = parse_size(mem_limit)
    else:
        mem_limit_i = int(mem_limit)

    guard = MemGuard(
        mem_limit_bytes=mem_limit_i,
        poll_interval=poll_interval,
        grace_kills=grace_kills,
    )

    if isinstance(cmd, str):
        return asyncio.run(guard.run_shell(cmd))
    return asyncio.run(guard.run(cmd))


def run_guarded_capture(
    cmd: list[str],
    mem_limit: str | int,
    *,
    poll_interval: float = 1.0,
    grace_kills: bool = True,
    capture_stdout: bool = True,
    capture_stderr: bool = True,
) -> tuple[int, bytes, bytes]:
    """
    Run ``cmd`` under RSS monitoring and capture stdout/stderr (synchronous).

    Args:
        cmd: argv list (no shell).
        mem_limit: Human-readable string or byte count (same as :func:`run_guarded`).
        poll_interval: Seconds between RSS checks.
        grace_kills: Try SIGTERM before SIGKILL.
        capture_stdout: If False, discard stdout (return ``b\"\"``).
        capture_stderr: If False, discard stderr (return ``b\"\"``).

    Returns:
        ``(exit_code, stdout_bytes, stderr_bytes)``. Exit code 137 if killed for memory.
    """
    _require_psutil()
    if isinstance(mem_limit, str):
        mem_limit_i = parse_size(mem_limit)
    else:
        mem_limit_i = int(mem_limit)

    guard = MemGuard(
        mem_limit_bytes=mem_limit_i,
        poll_interval=poll_interval,
        grace_kills=grace_kills,
    )

    out_dest = asyncio.subprocess.PIPE if capture_stdout else asyncio.subprocess.DEVNULL
    err_dest = asyncio.subprocess.PIPE if capture_stderr else asyncio.subprocess.DEVNULL

    async def _run() -> tuple[int, bytes, bytes]:
        return await guard.run_capture(cmd, stdout=out_dest, stderr=err_dest)

    return asyncio.run(_run())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Monitor a process tree's memory and kill if limit exceeded.",
        usage="python -m enroot.utils.mem_guard --limit 50G [--interval 1.0] -- <command> [args...]",
    )
    parser.add_argument(
        "--limit",
        "-l",
        required=True,
        help="Memory limit, e.g. '50G', '512M', '1T', '8000M'",
    )
    parser.add_argument(
        "--interval",
        "-i",
        type=float,
        default=1.0,
        help="Poll interval in seconds (default: 1.0)",
    )
    parser.add_argument(
        "--no-grace",
        action="store_true",
        help="Skip SIGTERM, go straight to SIGKILL",
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Command to run (use -- before it)",
    )
    args = parser.parse_args()

    cmd = args.command
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]

    if not cmd:
        parser.print_help()
        sys.exit(2)

    exit_code = run_guarded(
        cmd=cmd,
        mem_limit=args.limit,
        poll_interval=args.interval,
        grace_kills=not args.no_grace,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
