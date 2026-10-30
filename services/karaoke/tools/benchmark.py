"""Measure the real model, including startup and child-process RSS."""

import argparse
import json
from pathlib import Path
import platform
import tempfile
import threading
import time

import psutil

from services.karaoke.config import Settings, memory_ceiling
from services.karaoke.engine import SeparationEngine
from services.karaoke.resources import cgroup_memory_limit, verify_memory_limit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--models", type=Path, default=Path("/opt/models"))
    parser.add_argument("--threads", type=int, choices=(1, 2), default=1)
    parser.add_argument("--segment-size", type=int, default=128)
    parser.add_argument("--require-memory-limit", action="store_true")
    parser.add_argument("--env", choices=("dev", "production"), default="production")
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    args = parser.parse_args()
    policy = verify_memory_limit(memory_ceiling(args.env)) if args.require_memory_limit else {"hard_limit_bytes": cgroup_memory_limit()}
    stop = threading.Event()
    peaks = [0]

    def monitor():
        while not stop.wait(0.05):
            process = psutil.Process()
            current = process.memory_info().rss
            for child in process.children(recursive=True):
                try:
                    current += child.memory_info().rss
                except psutil.Error:
                    pass
            peaks[0] = max(peaks[0], current)

    thread = threading.Thread(target=monitor, daemon=True)
    thread.start()
    report = {"platform": platform.platform(), "machine": platform.machine(), "cpu_threads": args.threads,
              "resource_policy": policy, "input": args.input.name, "status": "failed"}
    try:
        with tempfile.TemporaryDirectory(prefix="karaoke-benchmark-") as directory:
            settings = Settings(api_key="benchmark-credentials-not-for-serving", environment=args.env, device=args.device,
                                model_dir=args.models.resolve(),
                                temp_dir=Path(directory), cpu_threads=args.threads, segment_size=args.segment_size)
            before = time.perf_counter()
            engine = SeparationEngine(settings)
            report["load_seconds"] = round(time.perf_counter() - before, 3)
            before = time.perf_counter()
            metadata, _ = engine.separate(args.input.resolve(), Path(directory), "benchmark")
            report.update(status="succeeded", processing_seconds=round(time.perf_counter() - before, 3),
                          audio_duration_seconds=metadata["duration_seconds"], model=engine.info())
            report["real_time_factor"] = round(report["processing_seconds"] / metadata["duration_seconds"], 3)
    except BaseException as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        stop.set()
        thread.join(timeout=2)
        report["peak_process_tree_rss_bytes"] = peaks[0]
        try:
            report["cgroup_peak_bytes"] = int(Path("/sys/fs/cgroup/memory.peak").read_text())
        except (OSError, ValueError):
            pass
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
