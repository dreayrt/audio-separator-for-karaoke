"""Exercise the real HTTP service. Output audio stays in the chosen backend directory."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import time

import httpx
import numpy as np
import soundfile as sf

from services.karaoke.examples.backend_client import KaraokeClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-device", choices=("cpu", "cuda"), default="cpu")
    args = parser.parse_args()
    credentials = dict(line.split("=", 1) for line in args.env_file.read_text().splitlines()
                       if line and not line.startswith("#") and "=" in line)
    client = KaraokeClient(args.url, credentials["AI_API_KEY"])
    args.output.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + 180
    while True:
        try:
            if client.session.get(args.url + "/health/ready", timeout=3).status_code == 200:
                break
        except httpx.HTTPError:
            pass
        if time.monotonic() > deadline:
            raise RuntimeError("Service did not become ready")
        time.sleep(1)
    info = client.session.get(args.url + "/v1/info").json()
    assert info["device"] == args.expected_device
    ceiling = 35 if info["environment"] == "production" else 30
    assert info["memory_policy"]["effective_percent"] <= ceiling
    assert httpx.get(args.url + "/v1/info").status_code == 401
    report = {"info": info, "checks": ["ready", "authentication", args.expected_device, "hard_memory_limit"]}
    before = time.perf_counter()
    with ThreadPoolExecutor(max_workers=1) as executor:
        job = executor.submit(client.separate, args.input, args.output)
        time.sleep(1)
        assert client.session.get(args.url + "/health/live", timeout=5).status_code == 200
        busy = client.session.post(args.url + "/v1/separate", data={"request_id": "busy-check"}, timeout=5)
        assert busy.status_code == 503
        metadata = job.result()
    report["separation_seconds"] = round(time.perf_counter() - before, 3)
    report["separation"] = metadata
    report["checks"] += ["streamed_zip", "stem_checksums", "concurrency_rejection", "health_during_inference"]
    before = time.perf_counter()
    reference = client.reference(args.output / "vocals.wav", args.output / "reference.json")
    report["reference_seconds"] = round(time.perf_counter() - before, 3)
    before = time.perf_counter()
    same = client.score(args.output / "vocals.wav", reference)
    report["score_seconds"] = round(time.perf_counter() - before, 3)
    if same["score"] is None:
        raise RuntimeError("Sample reference was not scoreable: " + same["quality"]["status"])
    assert same["score"]["overall"] >= 95
    silence = args.output / "silence.wav"
    sf.write(silence, np.zeros(22050 * 3), 22050)
    silent = client.score(silence, reference)
    assert silent["score"]["overall"] == 0
    report["self_comparison"] = same
    report["silence_comparison"] = silent
    report["checks"] += ["reference_api", "score_api", "same_audio_sanity", "silence_not_rewarded"]
    (args.output / "smoke-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "passed", "checks": report["checks"],
                      "separation_seconds": report["separation_seconds"],
                      "reference_seconds": report["reference_seconds"], "score_seconds": report["score_seconds"]}, indent=2))


if __name__ == "__main__":
    main()
