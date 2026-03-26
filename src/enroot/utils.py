import asyncio
import re
import shutil
import socket
import subprocess
import time
import uuid
import warnings
from typing import List, Optional, Dict, Any


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
    
async def run_enroot_async(
    args: List[str],
    capture: bool = True,
    check: bool = True,
    text: bool = True,
) -> str:
    """Async version of run_enroot. Same signature and behavior; use in async code."""
    cmd = ["enroot", *map(str, args)]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE if capture else asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,  # always capture stderr for error messages
    )
    out_bytes, err_bytes = await proc.communicate()
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
    cols = ["NAME", "PID", "COMM", "STATE", "STARTED", "TIME",
            "MNTNS", "USERNS", "COMMAND"]
    starts = {c: header.find(c) for c in cols if c in header}
    bounds = []
    for i, (c, s) in enumerate(sorted(starts.items(), key=lambda kv: kv[1])):
        e = sorted(starts.values())[i + 1] if i + 1 < len(starts) else None
        bounds.append((c, s, e))

    info: Dict[str, Dict[str, Any]] = {}
    cur: Optional[str] = None

    for ln in lines[1:]:
        if ln[starts["NAME"]] != " ":           # new container row
            cur = ln[starts["NAME"]:starts["PID"]].strip()
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


def list_containers_plain() -> Dict[str, Dict[str, Any]]:
    """Run 'enroot list' (no --fancy). Fast, minimal load. Returns container names with empty dicts."""
    out = run_enroot(["list"], check=False)
    return parse_list(out)


def list_containers_fancy(
    retries: int = 10,
    fallback_plain: bool = True,
) -> Dict[str, Dict[str, Any]]:
    """Run 'enroot list --fancy' with retries. Returns same structure as parse_list().

    'enroot list --fancy' can exit 1 with no stderr (e.g. no containers or no TTY).
    This wrapper retries a few times with short backoff, then optionally falls back
    to plain 'enroot list' (container names only, no PID/state info).
    """
    for attempt in range(retries):
        try:
            out = run_enroot(["list", "--fancy"], check=True)
            return parse_list(out)
        except RuntimeError:
            if attempt < retries - 1:
                time.sleep(0.5 * (attempt + 1))
                continue
            if fallback_plain:
                out = run_enroot(["list"], check=False)
                return parse_list(out)
            raise
    return {}  # unreachable


def run_enroot(
    args: List[str],
    capture: bool = True,
    check: bool = True,
    text: bool = True,
) -> str:
    """Run enroot command. Raises RuntimeError with stderr on non-zero exit when check=True.
    When ENROOT_ASYNC=1 and no event loop is running, uses run_enroot_async() internally.
    """
    from .config import ENROOT_ASYNC

    if ENROOT_ASYNC:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is None:
            return asyncio.run(run_enroot_async(args, capture=capture, check=check, text=text))

    cmd = ["enroot", *map(str, args)]
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.PIPE,  # always capture stderr for error messages
        text=text,
    )
    if proc.returncode != 0:
        err_msg = proc.stderr.strip() if proc.stderr else "(no stderr)"
        out_msg = proc.stdout.strip() if (capture and proc.stdout) else ""
        details = [f"exit code: {proc.returncode}", f"stderr: {err_msg}"]
        if out_msg:
            details.append(f"stdout: {out_msg}")
        if check:
            raise RuntimeError(
                f"enroot failed: {' '.join(args)}\n" + "\n".join(details)
            )
    return (proc.stdout.strip() if capture and proc.stdout else "")

def clear_enroot_containers() -> None:
    containers = parse_list(run_enroot(["list"], capture=True))
    for name in containers:
        run_enroot(["remove", "--force", name], capture=False)
    print("Cleared all enroot containers")