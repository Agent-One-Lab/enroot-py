import asyncio
import shutil
import subprocess
import uuid
import warnings
from typing import List, Optional, Dict, Any
import socket


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


def allocate_free_port() -> str:
    """Ask the kernel for a free TCP port and return it as a string."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return str(s.getsockname()[1])
    
async def run_enroot_async(args: List[str],
                capture: bool = True,
                check: bool = True,
                text: bool = True) -> str:
    cmd = ["enroot", *map(str, args)]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE if capture else asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE if capture else asyncio.subprocess.DEVNULL,
    )
    out_bytes, err_bytes = await proc.communicate()
    if check and proc.returncode:
        raise RuntimeError(f"$ {' '.join(cmd)}\n{err_bytes.decode()}")
    
    return out_bytes.decode().strip() if capture else ""

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


def run_enroot(args: List[str],
                capture: bool = True,
                check: bool = False,
                text: bool = True) -> str:
    # """
    # If called from sync code → run normally (blocking).
    # If called while an event-loop is running → delegate to a_run_enroot().
    # """
    # try:
    #     loop = asyncio.get_running_loop()
    # except RuntimeError:
    #     loop = None

    # if loop and loop.is_running():
    #     return loop.run_until_complete(a_run_enroot(args, capture, check, text))
    # else:
    proc = subprocess.run(
            ["enroot", *map(str, args)],
            stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
            stderr=subprocess.PIPE if capture else subprocess.DEVNULL,
        )
    if check and proc.returncode:
        raise RuntimeError(f"$ {' '.join(args)}\n{proc.stderr}")
    return proc.stdout.decode().strip() if capture else ""

def clear_enroot_containers() -> None:
    run_enroot(["remove", "--force", "$(enroot list)"], capture=False)
    print("Cleared all enroot containers")