"""Score-only integration client. The application's backend owns MongoDB and file storage."""

import argparse
import json
import os
from pathlib import Path
import uuid

import httpx

from services.karaoke.config import PRODUCTION_URL


class KaraokeClient:
    def __init__(self, base_url: str, api_key: str, read_timeout: float = 1800):
        self.url = base_url.rstrip("/")
        self.timeout = httpx.Timeout(connect=10, read=read_timeout, write=read_timeout, pool=30)
        self.session = httpx.Client(timeout=self.timeout)
        self.session.headers["Authorization"] = "Bearer " + api_key

    def close(self):
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def score(self, recording: Path, reference: Path, *, offset_ms=0, latency_ms=0):
        version = json.loads(reference.read_text(encoding="utf-8"))["reference_version"]
        timing = {"recording_start_offset_ms": offset_ms, "capture_latency_ms": latency_ms,
                  "expected_reference_version": version, "allow_octave_shift": True}
        with recording.open("rb") as audio, reference.open("rb") as reference_file:
            response = self.session.post(self.url + "/v1/score",
                                         files={"recording": (recording.name, audio),
                                                "reference": (reference.name, reference_file)},
                                         data={"timing": json.dumps(timing), "request_id": uuid.uuid4().hex},
                                         timeout=self.timeout)
        response.raise_for_status()
        return response.json()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("score",))
    parser.add_argument("--env", choices=("dev", "production"), default="dev")
    parser.add_argument("--url", help="Overrides KARAOKE_API_URL and the environment default")
    parser.add_argument("--key-file", type=Path, help="Private Docker env file; otherwise read AI_API_KEY")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--offset-ms", type=float, default=0)
    parser.add_argument("--latency-ms", type=float, default=0)
    parser.add_argument("--read-timeout", type=float, default=1800, help="Seconds; set using measured full-song latency")
    args = parser.parse_args()
    key = os.environ.get("AI_API_KEY", "")
    if args.key_file:
        for line in args.key_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("AI_API_KEY="):
                key = line.split("=", 1)[1]
    if not key:
        parser.error("Provide backend credentials through AI_API_KEY or --key-file")
    if args.read_timeout <= 0:
        parser.error("--read-timeout must be positive")
    base_url = args.url or os.environ.get("KARAOKE_API_URL") or (PRODUCTION_URL if args.env == "production" else "http://127.0.0.1:8000")
    client = KaraokeClient(base_url, key, read_timeout=args.read_timeout)
    if args.reference is None:
        parser.error("--reference is required")
    print(json.dumps(client.score(args.input, args.reference, offset_ms=args.offset_ms,
                                  latency_ms=args.latency_ms), indent=2))


if __name__ == "__main__":
    main()
