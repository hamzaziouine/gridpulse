"""Laptop safety for heavy local runs (local Spark, model training): Windows commit charge.

The team laptop has a 31.6 GB commit limit and has crashed once when several heavy jobs ran
together. Rule: start a heavy run only below 22 GB committed, and stop it above 28 GB.
`CommitWatchdog` enforces the second half in a background thread. Other platforms report None
and the guard does nothing.
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
from collections.abc import Callable

START_LIMIT_GB = 22.0
KILL_LIMIT_GB = 28.0


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [  # ctypes layout of MEMORYSTATUSEX
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def commit_gb() -> float | None:
    """Committed memory in GB (commit limit minus available commit), None off Windows."""
    if sys.platform != "win32":
        return None
    st = _MemoryStatusEx()
    st.dwLength = ctypes.sizeof(_MemoryStatusEx)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):  # type: ignore[attr-defined]
        return None
    return (st.ullTotalPageFile - st.ullAvailPageFile) / 1024**3


def require_headroom(limit_gb: float = START_LIMIT_GB) -> float | None:
    used = commit_gb()
    if used is not None and used >= limit_gb:
        raise SystemExit(f"commit charge {used:.1f} GB >= {limit_gb} GB: not starting a heavy run")
    return used


class CommitWatchdog(threading.Thread):
    """Calls `on_breach` (default: exit the process, which also ends the Spark JVM) when the
    commit charge goes above `limit_gb`."""

    def __init__(
        self,
        limit_gb: float = KILL_LIMIT_GB,
        interval_s: float = 5.0,
        on_breach: Callable[[float], None] | None = None,
    ) -> None:
        super().__init__(daemon=True, name="commit-watchdog")
        self.limit_gb, self.interval_s = limit_gb, interval_s
        self.on_breach = on_breach or self._exit
        self.peak_gb = 0.0
        self._halt = threading.Event()

    @staticmethod
    def _exit(used: float) -> None:
        print(f"commit charge {used:.1f} GB above the kill limit: stopping", file=sys.stderr)
        os._exit(3)

    def run(self) -> None:
        while not self._halt.is_set():
            used = commit_gb()
            if used is not None:
                self.peak_gb = max(self.peak_gb, used)
                if used > self.limit_gb:
                    self.on_breach(used)
                    return
            time.sleep(self.interval_s)

    def stop(self) -> None:
        self._halt.set()
