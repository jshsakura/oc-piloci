from __future__ import annotations

"""Tiny helpers for inspecting the host CPU budget the worker is allowed to use.

Pi 5 has 4 logical cores but real deployments often pin Gemma to fewer
(e.g. ``llama-server -t 3`` to leave one core free for the rest of the system).
The distillation scheduler has no way to read llama-server's threadcount, so we
fall back to the kernel-visible affinity and let the user override via env when
that estimate is wrong.
"""

import os


def detect_active_cores() -> int:
    """Return the number of CPU cores this process is *allowed* to schedule on.

    Order of precedence:
      1. ``PILOCI_AVAILABLE_CORES`` env override — for setups where the kernel
         can't see the constraint (e.g. ``llama-server -t 3`` reserves a core
         purely by convention, with no cgroup or affinity mask).
      2. ``os.sched_getaffinity(0)`` — honors cgroups, taskset, and isolcpus.
      3. ``os.cpu_count()`` — bottom fallback for platforms without sched_getaffinity.
      4. ``1`` — paranoid floor; nothing should report 0 cores.
    """
    override = os.environ.get("PILOCI_AVAILABLE_CORES", "").strip()
    if override:
        try:
            n = int(override)
            if n >= 1:
                return n
        except ValueError:
            pass
    try:
        return len(os.sched_getaffinity(0)) or os.cpu_count() or 1
    except (AttributeError, OSError):
        return os.cpu_count() or 1
