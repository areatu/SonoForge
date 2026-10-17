#!/usr/bin/env python3
"""Peak RAM/CPU sampler for sizing minimum/recommended system requirements.

Samples a target process tree and groups the samples into scenario segments so
a requirements table can be built from real peaks instead of guesses.

Usage:
  # spawn the app and sample it until it exits
  uv run python tools/measure_resources.py --run -- uv run sonoforge

  # attach to an already running app
  uv run python tools/measure_resources.py --pid 12345 --label "S0 idle"

While sampling, type a scenario label on stdin and press Enter to start a new
segment (``S1 open study``, ``S3 segmentation`` ...). Ctrl+C stops sampling,
terminates a spawned child, and prints the report.

Notes:
  * PSS (proportional set size) is reported when the platform exposes it
    (Linux smaps_rollup); otherwise RSS is used and the column is marked RSS*.
  * Peak RAM per segment is the sampled tree's own peak (VmHWM on Linux,
    peak_wset on Windows); ru_maxrss of the sampler itself is never reported
    because it describes this script, not the app.
  * CPU percentages for the process tree are per logical core (100% = one core
    fully busy); ``sys``/``core`` columns are for the whole machine.
"""

from __future__ import annotations

import argparse
import json
import platform
import queue
import signal
import subprocess
import sys
import threading
import time
from typing import Any

import psutil

MB = 1e6


def _ru_maxrss_bytes(*, children: bool = False) -> float:
    """Peak RSS as reported by the OS. Linux: KiB, macOS: bytes, Windows: none."""
    try:
        import resource
    except ImportError:  # Windows
        return 0.0
    which = resource.RUSAGE_CHILDREN if children else resource.RUSAGE_SELF
    try:
        value = resource.getrusage(which).ru_maxrss
    except (OSError, ValueError):
        return 0.0
    return float(value) if sys.platform == "darwin" else float(value) * 1024


def _vmhwm_bytes(pid: int) -> int:
    """Peak RSS of one process: Linux /proc/<pid>/status VmHWM, else 0."""
    try:
        with open(f"/proc/{pid}/status", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("VmHWM:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return 0
    return 0


def _peak_rss_bytes(procs: list[psutil.Process]) -> float:
    """Peak RSS of the sampled tree (sum of per-process peaks, an upper bound).

    Linux: VmHWM, Windows: peak_wset, macOS: 0 (no per-process peak available).
    """
    total = 0.0
    for proc in procs:
        try:
            peak = getattr(proc.memory_info(), "peak_wset", 0) or _vmhwm_bytes(proc.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        total += peak
    return total


def _host_info() -> dict[str, Any]:
    vm = psutil.virtual_memory()
    cpu_model = None
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("model name"):
                    cpu_model = line.split(":", 1)[1].strip()
                    break
    except OSError:
        cpu_model = platform.processor() or None
    return {
        "platform": platform.platform(),
        "cpu_model": cpu_model,
        "cores_physical": psutil.cpu_count(logical=False),
        "cores_logical": psutil.cpu_count(logical=True),
        "ram_total_gb": round(vm.total / 1e9, 1),
        "python": platform.python_version(),
        "psutil": psutil.__version__,
    }


def _sample(procs: list[psutil.Process]) -> dict[str, Any]:
    rss = 0
    pss = 0
    cpu = 0.0
    pss_ok = True
    for proc in procs:
        try:
            rss += proc.memory_info().rss
            cpu += proc.cpu_percent(interval=None)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if pss_ok:
            try:
                pss += proc.memory_full_info().pss
            except (psutil.AccessDenied, psutil.Error, NotImplementedError, OSError):
                pss_ok = False
    if not pss_ok:
        pss = rss
    sys_cpu = psutil.cpu_percent(interval=None)
    per_core = psutil.cpu_percent(percpu=True)
    return {
        "t": time.time(),
        "mem": pss if pss_ok else rss,
        "pss_ok": pss_ok,
        "rss": rss,
        "peak": _peak_rss_bytes(procs),
        "cpu": cpu,
        "sys_cpu": sys_cpu,
        "core_max": max(per_core) if per_core else 0.0,
    }


def _reader(labels: queue.Queue[str]) -> None:
    try:
        for line in sys.stdin:
            label = line.strip()
            if label:
                labels.put(label)
    except (OSError, ValueError):
        pass


def _fold(seg: dict[str, Any], sample: dict[str, Any]) -> None:
    seg["t1"] = sample["t"]
    seg["n"] += 1
    seg["mem_max"] = max(seg["mem_max"], sample["mem"])
    seg["mem_sum"] += sample["mem"]
    seg["rss_max"] = max(seg["rss_max"], sample["rss"])
    seg["cpu_max"] = max(seg["cpu_max"], sample["cpu"])
    seg["cpu_sum"] += sample["cpu"]
    seg["sys_max"] = max(seg["sys_max"], sample["sys_cpu"])
    seg["core_max"] = max(seg["core_max"], sample["core_max"])
    seg["peak_rss_end"] = max(seg["peak_rss_end"], sample["peak"])
    seg["pss_ok"] = seg["pss_ok"] and sample["pss_ok"]


def _new_segment(label: str) -> dict[str, Any]:
    now = time.time()
    return {
        "label": label,
        "t0": now,
        "t1": now,
        "n": 0,
        "mem_max": 0,
        "mem_sum": 0,
        "rss_max": 0,
        "cpu_max": 0.0,
        "cpu_sum": 0.0,
        "sys_max": 0.0,
        "core_max": 0.0,
        "pss_ok": True,
        "peak_rss_end": 0.0,
    }


def _merge(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse consecutive segments with the same label (repeated scenario runs)."""
    merged: list[dict[str, Any]] = []
    for seg in segments:
        if not merged or merged[-1]["label"] != seg["label"]:
            merged.append(dict(seg))
            continue
        last = merged[-1]
        n_prev = last["n"]
        last["t1"] = seg["t1"]
        last["n"] = n_prev + seg["n"]
        last["mem_max"] = max(last["mem_max"], seg["mem_max"])
        last["mem_sum"] += seg["mem_sum"]
        last["rss_max"] = max(last["rss_max"], seg["rss_max"])
        last["cpu_max"] = max(last["cpu_max"], seg["cpu_max"])
        last["cpu_sum"] += seg["cpu_sum"]
        last["sys_max"] = max(last["sys_max"], seg["sys_max"])
        last["core_max"] = max(last["core_max"], seg["core_max"])
        last["peak_rss_end"] = max(last["peak_rss_end"], seg["peak_rss_end"])
        last["pss_ok"] = last["pss_ok"] and seg["pss_ok"]
    return merged


def _report(segments: list[dict[str, Any]], host: dict[str, Any]) -> None:
    if not segments:
        print("No samples collected.")
        return
    unit = "mem" if segments[0]["pss_ok"] else "RSS*"
    print()
    print("== scenario segments ==")
    header = (
        f"{'label':<24} {'n':>5} {'wall':>8} {unit + ' max':>9} {unit + ' avg':>9} "
        f"{'CPU max':>9} {'CPU avg':>9} {'sys max':>9} {'core max':>9} {'peakRSS@end':>12}"
    )
    print(header)
    print("-" * len(header))
    for seg in segments:
        n = seg["n"] or 1
        wall = max(seg["t1"] - seg["t0"], 0.0)
        print(
            f"{seg['label']:<24} {seg['n']:>5} {wall:>7.1f}s "
            f"{seg['mem_max'] / MB:>8.1f}M {seg['mem_sum'] / n / MB:>8.1f}M "
            f"{seg['cpu_max']:>8.1f}% {seg['cpu_sum'] / n:>8.1f}% "
            f"{seg['sys_max']:>8.1f}% {seg['core_max']:>8.1f}% "
            f"{seg['peak_rss_end'] / MB:>11.1f}M"
        )
    print()
    print("== overall ==")
    tree_peak = max((s["peak_rss_end"] for s in segments), default=0.0)
    print(f"peak RSS of sampled process tree: {tree_peak / MB:.1f} MB")
    child_peak = _ru_maxrss_bytes(children=True)
    if child_peak:
        print(f"ru_maxrss (largest terminated child): {child_peak / MB:.1f} MB")
    best = max(segments, key=lambda s: s["mem_max"])
    print(f"highest segment peak: {best['label']} -> {best['mem_max'] / MB:.1f} MB")
    if not segments[0]["pss_ok"]:
        print("note: PSS unavailable on this platform, RSS was used instead (RSS*).")
    print(f"host: {host['platform']}")
    print(
        f"cpu: {host['cpu_model']} | cores {host['cores_physical']}p/{host['cores_logical']}l"
        f" | ram {host['ram_total_gb']} GB | python {host['python']} | psutil {host['psutil']}"
    )


def _dump_json(path: str, segments: list[dict[str, Any]], host: dict[str, Any]) -> None:
    out = []
    for seg in segments:
        n = seg["n"] or 1
        out.append(
            {
                "label": seg["label"],
                "wall_s": round(seg["t1"] - seg["t0"], 3),
                "samples": seg["n"],
                "mem_metric": "pss" if seg["pss_ok"] else "rss",
                "mem_peak_mb": round(seg["mem_max"] / MB, 1),
                "mem_avg_mb": round(seg["mem_sum"] / n / MB, 1),
                "rss_peak_mb": round(seg["rss_max"] / MB, 1),
                "cpu_peak_pct_one_core": round(seg["cpu_max"], 1),
                "cpu_avg_pct_one_core": round(seg["cpu_sum"] / n, 1),
                "system_cpu_peak_pct": round(seg["sys_max"], 1),
                "busiest_core_pct": round(seg["core_max"], 1),
                "peak_rss_at_end_mb": round(seg["peak_rss_end"] / MB, 1),
            }
        )
    payload = {
        "host": host,
        "overall_peak_rss_mb": round(max((s["peak_rss_end"] for s in segments), default=0.0) / MB, 1),
        "segments": out,
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print(f"json written: {path}")


def _normalize_argv(argv: list[str]) -> list[str]:
    """Accept ``--run -- CMD`` as well as ``--run CMD`` (argparse.REMAINDER drops a leading ``--``)."""
    out: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        out.append(token)
        if token == "--run" and index + 1 < len(argv) and argv[index + 1] == "--":
            index += 1
        index += 1
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pid", type=int, help="attach to a running process")
    parser.add_argument("--run", nargs=argparse.REMAINDER, metavar="CMD", help="spawn CMD and sample it")
    parser.add_argument("--label", default="S0", help="initial scenario label (default: S0)")
    parser.add_argument("--interval", type=float, default=0.2, help="sample interval in seconds")
    parser.add_argument("--json", dest="json_path", help="write results to this JSON file")
    args = parser.parse_args(_normalize_argv(argv if argv is not None else sys.argv[1:]))

    if (args.pid is None) == (not args.run):
        parser.error("specify exactly one of --pid or --run CMD")

    host = _host_info()
    child: subprocess.Popen[bytes] | None = None
    pid = args.pid
    if args.run:
        cmd = args.run[1:] if args.run[0] == "--" else args.run
        if not cmd:
            parser.error("--run needs a command after --")
        print(f"spawning: {' '.join(cmd)}")
        # DEVNULL: the sampler owns stdin for scenario labels, a child must not eat them.
        child = subprocess.Popen(cmd, stdin=subprocess.DEVNULL)  # noqa: S603
        pid = child.pid

    assert pid is not None
    try:
        root = psutil.Process(pid)
    except psutil.NoSuchProcess:
        print(f"process {pid} not found", file=sys.stderr)
        if child is not None:
            child.terminate()
        return 1

    labels: queue.Queue[str] = queue.Queue()
    if not sys.stdin.closed:
        threading.Thread(target=_reader, args=(labels,), daemon=True).start()

    print(f"sampling pid {pid} every {args.interval}s — type a label + Enter to mark a scenario, Ctrl+C to stop")
    segments: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    label = args.label
    stopping = False
    # psutil keeps the cpu_percent delta per Process object: rebuilding objects
    # every tick would reset the delta and report 0% for the whole run.
    proc_cache: dict[int, psutil.Process] = {root.pid: root}

    try:
        while True:
            try:
                while True:
                    label = labels.get_nowait()
                    if current is not None:
                        segments.append(current)
                    current = None
            except queue.Empty:
                pass

            try:
                if child is not None:
                    if child.poll() is not None:  # reaps our own child, no zombie spin
                        break
                elif root.status() == psutil.STATUS_ZOMBIE:
                    break
                tree = [root, *root.children(recursive=True)]
            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                break

            procs: list[psutil.Process] = []
            for proc in tree:
                cached = proc_cache.get(proc.pid)
                if cached is None:
                    cached = proc
                    proc_cache[proc.pid] = cached
                procs.append(cached)
            for stale in [key for key in proc_cache if key not in {p.pid for p in tree}]:
                del proc_cache[stale]

            sample = _sample(procs)
            if current is None:
                current = _new_segment(label)
            _fold(current, sample)

            time.sleep(args.interval)
    except KeyboardInterrupt:
        stopping = True
        print("\nstopping…")
        # ``uv run`` and shells may deliver SIGINT twice; the second one must not
        # interrupt the cleanup below and lose the collected samples.
        signal.signal(signal.SIGINT, signal.SIG_IGN)

    if current is not None:
        segments.append(current)
    segments = _merge(segments)

    try:
        if child is not None and child.poll() is None:
            print("terminating child…")
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
    except KeyboardInterrupt:
        if child is not None:
            child.kill()
    except OSError as exc:
        print(f"cleanup warning: {exc}")
    if stopping:
        print("(child terminated by Ctrl+C)" if child is not None else "")

    _report(segments, host)
    if args.json_path:
        _dump_json(args.json_path, segments, host)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
