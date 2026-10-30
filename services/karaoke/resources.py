"""Report memory usage constraints and validate only explicitly selected limits."""

import math
from pathlib import Path

def docker_budget(host_bytes: int, percent: int = 100) -> int:
    if host_bytes <= 0 or not 1 <= percent <= 100:
        raise ValueError("Invalid memory budget")
    # 10% headroom below the user's ceiling; MiB rounding is always downwards.
    return math.floor(host_bytes * percent / 100 * 0.90 / 1024**2) * 1024**2


def cgroup_memory_limit() -> int | None:
    for path in (Path("/sys/fs/cgroup/memory.max"), Path("/sys/fs/cgroup/memory/memory.limit_in_bytes")):
        try:
            value = path.read_text().strip()
            if value != "max":
                amount = int(value)
                if 0 < amount < 2**60:
                    return amount
        except (OSError, ValueError):
            pass
    return None


def host_memory_bytes() -> int:
    import psutil
    return psutil.virtual_memory().total


def verify_memory_limit(percent: int | None = None) -> dict:
    host = host_memory_bytes()
    limit = cgroup_memory_limit()
    if percent is not None and limit is None:
        raise RuntimeError("No hard memory limit detected. Run dev/production through the Docker launcher.")
    if percent is not None and limit > host * percent / 100:
        raise RuntimeError("Container memory limit exceeds the allowed host-memory percentage")
    return {"host_memory_bytes": host, "hard_limit_bytes": limit, "ceiling_percent": percent,
            "policy": "explicit-percentage" if percent is not None else "no-default-memory-cap",
            "effective_percent": round(limit / host * 100, 3) if limit else None}
