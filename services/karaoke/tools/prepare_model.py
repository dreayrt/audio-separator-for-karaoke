"""Download the pinned model/config at build time, never while serving requests."""

import argparse
import json
import os
from pathlib import Path

import requests

from services.karaoke.assets import (CONFIG_FILENAME, CONFIG_SHA256, CONFIG_URL, MODEL_FILENAME,
                                    MODEL_SHA256, MODEL_URL, PROFILE, load_bundle, sha256_file)


def download(url: str, target: Path) -> None:
    if target.is_file():
        return
    partial = target.with_suffix(target.suffix + ".partial")
    try:
        with requests.get(url, stream=True, timeout=(30, 180)) as response:
            response.raise_for_status()
            size = 0
            with partial.open("wb") as handle:
                for block in response.iter_content(1024 * 1024):
                    if block:
                        handle.write(block)
                        size += len(block)
            declared = response.headers.get("Content-Length")
            if size == 0 or (declared is not None and size != int(declared)):
                raise ValueError("Incomplete asset download")
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path(".karaoke-models"))
    parser.add_argument("--expected-model-sha256", default=os.getenv("AI_EXPECTED_MODEL_SHA256", MODEL_SHA256))
    parser.add_argument("--expected-config-sha256", default=os.getenv("AI_EXPECTED_CONFIG_SHA256", CONFIG_SHA256))
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    items = {}
    for role, filename, url, expected in (
        ("model", MODEL_FILENAME, MODEL_URL, args.expected_model_sha256),
        ("config", CONFIG_FILENAME, CONFIG_URL, args.expected_config_sha256),
    ):
        target = args.directory / filename
        print(f"Preparing {role}: {filename}", flush=True)
        download(url, target)
        digest = sha256_file(target)
        if expected and digest != expected.lower():
            raise ValueError(f"{role} SHA256 mismatch; remove the asset and download from the verified source again")
        items[role] = {"filename": filename, "sha256": digest, "source": url, "bytes": target.stat().st_size}
    manifest = {"schema_version": 1, "profile": PROFILE, "architecture": "MDXC", **items}
    (args.directory / "bundle.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    load_bundle(args.directory)
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == "__main__":
    main()
