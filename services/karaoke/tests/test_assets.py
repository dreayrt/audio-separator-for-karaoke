import hashlib
import json

import pytest

from services.karaoke.assets import load_bundle


def test_offline_bundle_checks_actual_contents_and_rejects_path_escape(tmp_path):
    manifest = {"schema_version": 1, "profile": "karaoke-v1", "architecture": "MDXC"}
    for role, name in (("model", "weights.ckpt"), ("config", "model.yaml")):
        data = role.encode()
        (tmp_path / name).write_bytes(data)
        manifest[role] = {"filename": name, "sha256": hashlib.sha256(data).hexdigest()}
    (tmp_path / "bundle.json").write_text(json.dumps(manifest))
    assert load_bundle(tmp_path)["profile"] == "karaoke-v1"
    (tmp_path / "weights.ckpt").write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="corrupted"):
        load_bundle(tmp_path)
    manifest["model"]["filename"] = "../escape.ckpt"
    (tmp_path / "bundle.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="filename"):
        load_bundle(tmp_path)
