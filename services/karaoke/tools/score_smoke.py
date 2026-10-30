"""Check the score-only API with an already prepared recording/reference pair."""

import argparse
import json
import os
from pathlib import Path
import time

from services.karaoke.examples.backend_client import KaraokeClient


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--env-file", type=Path, help="Private env file with AI_API_KEY")
    parser.add_argument("--recording", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--read-timeout", type=float, default=1800)
    args = parser.parse_args()
    key = os.environ.get("AI_API_KEY", "")
    if args.env_file:
        for line in args.env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("AI_API_KEY="):
                key = line.split("=", 1)[1]
    if not key:
        parser.error("Provide the backend key through AI_API_KEY or --env-file")
    if not args.recording.is_file() or not args.reference.is_file():
        parser.error("--recording and --reference must point to existing files")

    started = time.perf_counter()
    client = KaraokeClient(args.url, key, read_timeout=args.read_timeout)
    try:
        ready = client.session.get(args.url.rstrip("/") + "/health/ready", timeout=10)
        ready.raise_for_status()
        info_response = client.session.get(args.url.rstrip("/") + "/v1/info", timeout=10)
        info_response.raise_for_status()
        info = info_response.json()
        if info.get("service_mode") != "score-only":
            raise RuntimeError("The API is not the expected score-only service")
        score = client.score(args.recording, args.reference)
        report = {"status": "completed", "service": info, "result": score,
                  "elapsedSeconds": round(time.perf_counter() - started, 3)}
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        client.close()


if __name__ == "__main__":
    main()
