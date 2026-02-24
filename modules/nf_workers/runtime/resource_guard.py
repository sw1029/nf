from __future__ import annotations

import sys

try:
    import resource  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    resource = None  # type: ignore[assignment]


def get_process_rss_mb() -> float:
    if resource is not None:
        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform == "darwin":
            return float(usage) / (1024 * 1024)
        return float(usage) / 1024

    if sys.platform.startswith("win"):
        try:
            import ctypes
            import ctypes.wintypes

            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("cb", ctypes.wintypes.DWORD),
                    ("PageFaultCount", ctypes.wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.wintypes.SIZE_T),
                    ("WorkingSetSize", ctypes.wintypes.SIZE_T),
                    ("QuotaPeakPagedPoolUsage", ctypes.wintypes.SIZE_T),
                    ("QuotaPagedPoolUsage", ctypes.wintypes.SIZE_T),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.wintypes.SIZE_T),
                    ("QuotaNonPagedPoolUsage", ctypes.wintypes.SIZE_T),
                    ("PagefileUsage", ctypes.wintypes.SIZE_T),
                    ("PeakPagefileUsage", ctypes.wintypes.SIZE_T),
                ]

            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            ok = ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
            if ok:
                return float(counters.WorkingSetSize) / (1024 * 1024)
        except Exception:  # noqa: BLE001
            return 0.0

    return 0.0


def memory_pressure(max_ram_mb: int) -> bool:
    if max_ram_mb <= 0:
        return False
    usage_mb = get_process_rss_mb()
    if usage_mb <= 0:
        return False
    return usage_mb > max_ram_mb


def estimate_index_mb(text: str, chunk_count: int) -> float:
    text_mb = len(text.encode("utf-8")) / (1024 * 1024)
    return text_mb * 2.0 + chunk_count * 0.001
