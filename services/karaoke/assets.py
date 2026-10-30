"""A self-contained, checksummed model bundle; no model discovery at runtime."""

import hashlib
import json
from pathlib import Path


MODEL_FILENAME = "mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt"
CONFIG_FILENAME = "mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956_config.yaml"
MODEL_URL = f"https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/{MODEL_FILENAME}"
CONFIG_URL = f"https://github.com/nomadkaraoke/python-audio-separator/releases/download/model-configs/{CONFIG_FILENAME}"
PROFILE = "karaoke-v1"
MODEL_SHA256 = "1de20d459332fe8869aeb01327a31df0032262706e1365114e852dc271779813"
CONFIG_SHA256 = "b35077d94861f068097cce1a5e54633c055e7dcc2613eade4e4dc7c7c9c3f48b"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")


def load_bundle(directory: Path) -> dict:
    manifest = json.loads((directory / "bundle.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or manifest.get("profile") != PROFILE:
        raise ValueError("Unsupported model bundle")
    for role in ("model", "config"):
        item = manifest[role]
        name = item["filename"]
        if Path(name).name != name or "/" in name or "\\" in name:
            raise ValueError("Invalid bundle filename")
        path = directory / name
        if not path.is_file() or path.is_symlink() or sha256_file(path) != item["sha256"]:
            raise ValueError(f"Missing or corrupted {role} asset")
    if manifest.get("architecture") != "MDXC":
        raise ValueError("This service supports only the packaged MDXC profile")
    return manifest
