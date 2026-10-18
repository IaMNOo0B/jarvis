"""
JARVIS Diagnostics — psutil + nvidia-smi snapshots.

Feeds three consumers:
  * the run_diagnostics tool (spoken summary for sir)
  * the HUD gauges (light() every 2 s)
  * the proactive scheduler (briefing system line)
"""

import os
import shutil
import subprocess
import time

import psutil


class Diagnostics:
    def __init__(self):
        self._last_net = psutil.net_io_counters()
        self._last_net_ts = time.time()
        psutil.cpu_percent(interval=None)  # prime the counter

    # ------------------------------------------------------------------ gauges
    def light(self) -> dict:
        """Fast snapshot for the HUD. Numbers only, no subprocess fan-out."""
        now = time.time()
        net = psutil.net_io_counters()
        dt = max(now - self._last_net_ts, 0.5)
        rx = (net.bytes_recv - self._last_net.bytes_recv) / dt
        tx = (net.bytes_sent - self._last_net.bytes_sent) / dt
        self._last_net, self._last_net_ts = net, now
        bat = psutil.sensors_battery()
        return {
            "cpu": psutil.cpu_percent(interval=None),
            "mem": psutil.virtual_memory().percent,
            "net_rx": rx,
            "net_tx": tx,
            "battery": None if bat is None else bat.percent,
            "charging": None if bat is None else bat.power_plugged,
            "ts": now,
        }

    # ------------------------------------------------------------------- full
    def full(self) -> dict:
        vm = psutil.virtual_memory()
        du = None
        try:
            # the Windows system drive (C:, D:, …) — never assume it exists
            drive = (os.environ.get("SystemDrive", "C:") + "/"
                     if os.name == "nt" else "/")
            du = shutil.disk_usage(drive)
        except Exception:
            pass
        bat = psutil.sensors_battery()
        data = {
            "cpu_percent": psutil.cpu_percent(interval=0.6),
            "cpu_cores": psutil.cpu_count(logical=True),
            "mem_total_gb": round(vm.total / 1e9, 1),
            "mem_used_gb": round(vm.used / 1e9, 1),
            "mem_percent": vm.percent,
            "disk_c_used_percent": (None if du is None
                                    else round(du.used / du.total * 100, 1)),
            "disk_c_free_gb": (None if du is None else round(du.free / 1e9, 1)),
            "battery_percent": None if bat is None else bat.percent,
            "battery_plugged": None if bat is None else bat.power_plugged,
            "top_processes": self.top_processes(5),
            "gpu": self._gpu(),
        }
        return data

    def top_processes(self, n: int = 5) -> list:
        procs = []
        for p in psutil.process_iter(["name", "cpu_percent", "memory_percent"]):
            try:
                procs.append(p.info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        procs.sort(key=lambda x: (x.get("cpu_percent") or 0), reverse=True)
        return procs[:n]

    @staticmethod
    def _gpu():
        exe = shutil.which("nvidia-smi")
        if not exe:
            return None
        try:
            out = subprocess.run(
                [exe, "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=3,
            )
            parts = [p.strip() for p in out.stdout.strip().split(",")]
            if len(parts) == 4:
                return {
                    "util": float(parts[0]),
                    "mem_used_mb": float(parts[1]),
                    "mem_total_mb": float(parts[2]),
                    "temp_c": float(parts[3]),
                }
        except Exception:
            return None
        return None

    # ------------------------------------------------------------------ speech
    def summary_text(self) -> str:
        """Spoken 'running diagnostics' report — short, British, precise."""
        d = self.full()
        bits = [
            f"CPU at {d['cpu_percent']:.0f} percent across {d['cpu_cores']} cores",
            f"memory {d['mem_percent']:.0f} percent used with {d['mem_used_gb']} of {d['mem_total_gb']} gigabytes",
        ]
        if d.get("disk_c_used_percent") is not None:
            bits.append(f"disk C at {d['disk_c_used_percent']:.0f} percent, "
                        f"{d['disk_c_free_gb']} gigabytes free")
        if d["battery_percent"] is not None:
            state = "charging" if d["battery_plugged"] else "on battery"
            bits.append(f"battery {d['battery_percent']:.0f} percent, {state}")
        g = d["gpu"]
        if g:
            bits.append(
                f"GPU {g['util']:.0f} percent utilised, "
                f"{g['mem_used_mb'] / 1000:.1f} of {g['mem_total_mb'] / 1000:.1f} gigabytes, "
                f"{g['temp_c']:.0f} degrees"
            )
        hot = ", ".join(
            f"{p['name']} {p['cpu_percent']:.0f}%" for p in d["top_processes"][:3]
            if (p.get("cpu_percent") or 0) > 5
        )
        text = "Diagnostics complete, sir. " + ", ".join(bits) + "."
        if hot:
            text += f" Heaviest processes: {hot}."
        return text


# process-wide instance (thread-safe enough: all calls are read-only snapshots)
diagnostics = Diagnostics()


def snapshot_text() -> str:
    return diagnostics.summary_text()
