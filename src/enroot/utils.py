import asyncio
import math
import re
import shlex
import shutil
import socket
import subprocess
import time
import uuid
import warnings
from typing import List, Optional, Dict, Any

from . import errors


def systemd_prefix(cpus: Optional[float], mem: Optional[str | int]) -> List[str]:
    """Return ['systemd-run', …] args or [] if no limits requested/available."""
    if cpus is None and mem is None:
        return []
    if shutil.which("systemd-run") is None:
        warnings.warn("cpu_count/mem_limit ignored: systemd-run not found")
        return []

    args = ["systemd-run", "--user", "--scope"]
    if mem is not None:
        mem_val = f"{mem}" if isinstance(mem, (str, int)) else str(int(mem))
        args += ["-p", f"MemoryMax={mem_val}"]
    if cpus is not None:
        quota = int(float(cpus) * 100)  # 1 CPU = 100 %
        args += ["-p", f"CPUQuota={quota}%"]
    return args


def mem_limit_to_bytes(mem: str | int) -> int:
    """
    Parse docker-style memory limits into bytes for prlimit --as (RLIMIT_AS).
    int is treated as bytes; str supports optional k/m/g suffix (e.g. '512m', '1G').
    Returns 0 for unlimited (caller may skip prlimit).
    """
    if isinstance(mem, int):
        if mem < 0:
            raise ValueError("mem_limit must be non-negative")
        return mem
    s = str(mem).strip().lower()
    if not s:
        raise ValueError("mem_limit is empty")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([kmg]?)b?", s)
    if not m:
        raise ValueError(f"invalid mem_limit: {mem!r}")
    val = float(m.group(1))
    suf = m.group(2) or ""
    mult = {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3}[suf]
    out = int(val * mult)
    if out < 0:
        raise ValueError("mem_limit must be non-negative")
    return out


def allocate_free_port() -> str:
    """Ask the kernel for a free TCP port and return it as a string."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return str(s.getsockname()[1])


def _host_argv_with_timeout(argv: List[str], timeout: float) -> List[str]:
    """
    Wrap a full host argv in ``timeout`` + ``sh -c`` so the workload is signaled on expiry.

    Using ``subprocess.run(..., timeout=…)`` alone only kills the local waiter; the underlying
    work may continue unless the process tree is terminated. The ``timeout`` utility does that.
    """
    secs = max(1, int(math.ceil(float(timeout))))
    inner = " ".join(shlex.quote(str(a)) for a in argv)
    shell_line = f"timeout {secs} sh -c {shlex.quote(inner)}"
    return ["sh", "-c", shell_line]


async def run_enroot_async(
    args: List[str],
    capture: bool = True,
    check: bool = True,
    text: bool = True,
    timeout: float | None = None,
) -> str:
    """Async version of :func:`run_enroot` (same signature/behavior, except always uses subprocess APIs)."""
    cmd = ["enroot", *map(str, args)]
    if timeout is not None:
        cmd = _host_argv_with_timeout(cmd, timeout)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE if capture else asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,  # always capture stderr for error messages
    )
    out_bytes, err_bytes = await proc.communicate()
    if proc.returncode == 124 and timeout is not None:
        raise errors.TimeoutError(
            f"enroot command timed out after {timeout}s: enroot {' '.join(map(str, args))}"
        )
    if proc.returncode != 0:
        err_msg = (err_bytes.decode().strip() if err_bytes else "(no stderr)").strip()
        out_msg = (out_bytes.decode().strip() if (capture and out_bytes) else "").strip()
        details = [f"exit code: {proc.returncode}", f"stderr: {err_msg}"]
        if out_msg:
            details.append(f"stdout: {out_msg}")
        if check:
            raise RuntimeError(
                f"enroot failed: {' '.join(args)}\n" + "\n".join(details)
            )
    return (out_bytes.decode().strip() if capture and out_bytes else "")


def random_name(prefix: str = "cnt") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def parse_list(text: str) -> Dict[str, Dict[str, Any]]:
    """Handle both `enroot list` (plain names) and `list --fancy`."""
    lines = [ln.strip("\n") for ln in text.splitlines() if ln.strip()]
    if not lines:
        return {}

    # No header → simple list of names
    if not lines[0].lstrip().startswith("NAME"):
        return {ln.strip(): {} for ln in lines}

    header = lines[0]
    cols = ["NAME", "PID", "COMM", "STATE", "STARTED", "TIME", "MNTNS", "USERNS", "COMMAND"]
    starts = {c: header.find(c) for c in cols if c in header}
    bounds = []
    for i, (c, s) in enumerate(sorted(starts.items(), key=lambda kv: kv[1])):
        e = sorted(starts.values())[i + 1] if i + 1 < len(starts) else None
        bounds.append((c, s, e))

    info: Dict[str, Dict[str, Any]] = {}
    cur: Optional[str] = None
    for ln in lines[1:]:
        if ln[starts["NAME"]] != " ":  # new container row
            cur = ln[starts["NAME"] : starts["PID"]].strip()
            info[cur] = {"pids": []}
        if cur is None:
            continue
        for col, s, e in bounds:
            field = ln[s:e].strip()
            if not field:
                continue
            if col == "PID" and field.isdigit():
                info[cur]["pids"].append(int(field))
            else:
                info[cur][col.lower()] = field
    return info


def list_containers_plain(
    strict: bool | None = None,
) -> Dict[str, Dict[str, Any]]:
    """Run 'enroot list' (no --fancy). Fast, minimal load."""
    out = run_enroot(
        ["list"],
        check=(strict if strict is not None else True),
    )
    return parse_list(out)


async def list_containers_plain_async(
    strict: bool | None = None,
) -> Dict[str, Dict[str, Any]]:
    """Async variant of :func:`list_containers_plain`."""
    out = await run_enroot_async(
        ["list"],
        check=(strict if strict is not None else True),
    )
    return parse_list(out)


def list_containers_fancy(
    retries: int = 10,
    fallback_plain: bool = True,
    strict: bool | None = None,
) -> Dict[str, Dict[str, Any]]:
    """Run 'enroot list --fancy' with retries, optionally falling back to plain list."""
    for attempt in range(retries):
        try:
            out = run_enroot(
                ["list", "--fancy"],
                check=True,
            )
            return parse_list(out)
        except RuntimeError:
            if attempt < retries - 1:
                time.sleep(0.5 * (attempt + 1))
                continue
            if fallback_plain:
                out = run_enroot(
                    ["list"],
                    check=(strict if strict is not None else True),
                )
                return parse_list(out)
            raise
    return {}  # unreachable


async def list_containers_fancy_async(
    retries: int = 10,
    fallback_plain: bool = True,
    strict: bool | None = None,
) -> Dict[str, Dict[str, Any]]:
    """Async variant of :func:`list_containers_fancy`."""
    for attempt in range(retries):
        try:
            out = await run_enroot_async(
                ["list", "--fancy"],
                check=True,
            )
            return parse_list(out)
        except RuntimeError:
            if attempt < retries - 1:
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            if fallback_plain:
                out = await run_enroot_async(
                    ["list"],
                    check=(strict if strict is not None else True),
                )
                return parse_list(out)
            raise
    return {}  # unreachable


def run_enroot(
    args: List[str],
    capture: bool = True,
    check: bool = True,
    text: bool = True,
    timeout: float | None = None,
) -> str:
    """Run an enroot command and return stdout text.

    If the command exits non-zero and `check=True`, raises RuntimeError. If `timeout` is provided,
    wraps the host argv in shell `timeout` and maps exit code 124 to errors.TimeoutError.
    """
    from .config import ENROOT_ASYNC

    if ENROOT_ASYNC:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is None:
            return asyncio.run(
                run_enroot_async(
                    args,
                    capture=capture,
                    check=check,
                    text=text,
                    timeout=timeout,
                )
            )

    cmd = ["enroot", *map(str, args)]
    if timeout is not None:
        cmd = _host_argv_with_timeout(cmd, timeout)

    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=text,
    )

    if proc.returncode == 124 and timeout is not None:
        raise errors.TimeoutError(
            f"enroot command timed out after {timeout}s: enroot {' '.join(map(str, args))}"
        )

    if proc.returncode != 0:
        err_msg = proc.stderr.strip() if proc.stderr else "(no stderr)"
        out_msg = proc.stdout.strip() if (capture and proc.stdout) else ""
        details = [f"exit code: {proc.returncode}", f"stderr: {err_msg}"]
        if out_msg:
            details.append(f"stdout: {out_msg}")
        if check:
            raise RuntimeError(f"enroot failed: {' '.join(args)}\n" + "\n".join(details))

    return (proc.stdout.strip() if capture and proc.stdout else "")


def clear_enroot_containers() -> None:
    containers = parse_list(run_enroot(["list"], capture=True))
    for name in containers:
        run_enroot(["remove", "--force", name], capture=False)
    print("Cleared all enroot containers")

