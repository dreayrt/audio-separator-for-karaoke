"""Local preparation adapter with auto-selected CPU/CUDA and offline model assets."""

import hashlib
import logging
from pathlib import Path

from services.karaoke.assets import PROFILE, canonical_json, load_bundle, sha256_file
from services.karaoke.audio import decode, inspect_wav
from services.karaoke.errors import ServiceError


def configure_device(settings, torch):
    """Explicit CUDA never silently falls back; production cannot select CUDA."""
    if settings.environment == "production" and settings.device != "cpu":
        raise RuntimeError("Production must use CPU")
    if settings.device == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is unavailable. Use the GPU image with --gpus all, or select --device cpu for dev.")
        torch.cuda.set_per_process_memory_fraction(settings.gpu_memory_fraction, 0)
        return torch.device("cuda:0")
    return torch.device("cpu")


class SeparationEngine:
    def __init__(self, settings):
        self.settings = settings
        self.manifest = load_bundle(settings.model_dir)
        import torch
        device = configure_device(settings, torch)
        self.device = device
        self.device_name = torch.cuda.get_device_name(device) if device.type == "cuda" else "CPU"
        torch.set_num_threads(settings.cpu_threads)
        try:
            torch.set_num_interop_threads(1)
        except RuntimeError:
            pass
        from audio_separator.separator import Separator

        manifest = self.manifest

        class OfflineSeparator(Separator):
            def preload_onnxruntime_dependencies(inner_self):
                # This profile uses PyTorch; ONNX Runtime CUDA libraries are unnecessary.
                return None

            def setup_torch_device(inner_self, system_info):
                inner_self.torch_device_cpu = torch.device("cpu")
                inner_self.torch_device = device
                inner_self.onnx_execution_provider = ["CPUExecutionProvider"]

            def download_model_files(inner_self, filename):
                if filename != manifest["model"]["filename"]:
                    raise ValueError("Only the packaged model is allowed")
                inner_self.model_is_uvr_vip = False
                inner_self.model_friendly_name = manifest["profile"]
                return (filename, manifest["architecture"], manifest["profile"],
                        str(settings.model_dir / filename), str(settings.model_dir / manifest["config"]["filename"]))

            def download_file_if_not_exists(inner_self, url, output_path):
                if not Path(output_path).is_file():
                    raise RuntimeError("Offline model bundle is incomplete; runtime downloads are disabled")

        self.separator = OfflineSeparator(
            model_file_dir=str(settings.model_dir), output_dir=str(settings.temp_dir), output_format="WAV",
            use_soundfile=True, use_autocast=False, use_torch_compile=False, use_native_fp16=False,
            chunk_duration=settings.chunk_seconds, log_level=logging.WARNING,
            mdxc_params={"segment_size": settings.segment_size, "override_model_segment_size": True,
                         "batch_size": 1, "overlap": settings.overlap, "pitch_shift": 0},
        )
        self.separator.load_model(self.manifest["model"]["filename"])
        if self.separator.model_instance.torch_device.type != settings.device:
            raise RuntimeError("Loaded model device does not match the environment configuration")

    def info(self) -> dict:
        parameters = {"segment_size": self.settings.segment_size, "overlap": self.settings.overlap,
                      "chunk_seconds": self.settings.chunk_seconds, "batch_size": 1, "sample_rate": 44100,
                      "device": self.device.type, "precision": "float32", "chunking": "sample-exact-v1"}
        return {"profile": PROFILE, "model_filename": self.manifest["model"]["filename"],
                "model_version": self.manifest["model"]["sha256"],
                "config_version": hashlib.sha256(canonical_json({"asset": self.manifest["config"]["sha256"],
                                                                        "parameters": parameters})).hexdigest(),
                "device": self.device.type, "device_name": self.device_name,
                "gpu_memory_fraction": self.settings.gpu_memory_fraction if self.device.type == "cuda" else None,
                "cpu_threads": self.settings.cpu_threads, "parameters": parameters}

    def separate(self, source: Path, work: Path, request_id: str) -> tuple[dict, dict[str, Path]]:
        source_hash = sha256_file(source)
        wave = work / "decoded.wav"
        source_info = decode(source, wave, self.settings)
        if source_info["rms_dbfs"] < -75:
            raise ServiceError("SILENT_AUDIO", "The source audio is silent")
        output = work / "outputs"
        output.mkdir()
        self.separator.output_dir = str(output)
        self.separator.model_instance.output_dir = str(output)
        try:
            self.separator.separate(str(wave), custom_output_names={"Vocals": "vocals", "Instrumental": "instrumental"})
        except Exception as exc:
            raise ServiceError("SEPARATION_FAILED", "The model could not separate this audio", 500) from exc
        files = {name: output / f"{name}.wav" for name in ("instrumental", "vocals")}
        for path in files.values():
            if not path.is_file():
                raise ServiceError("MODEL_OUTPUT_INVALID", "The model did not produce both required stems", 500)
            info = inspect_wav(path, self.settings.max_duration_seconds)
            if info["sample_rate"] != source_info["sample_rate"] or abs(info["frames"] - source_info["frames"]) > 2:
                raise ServiceError("MODEL_OUTPUT_MISALIGNED", "Stem duration does not match the source timeline", 500)
        metadata = {"request_id": request_id, **self.info(), "source_hash": source_hash,
                    "duration_seconds": source_info["duration_seconds"], "sample_rate": source_info["sample_rate"],
                    "files": {name: path.name for name, path in files.items()},
                    "file_hashes": {name: sha256_file(path) for name, path in files.items()},
                    "warnings": ["Vocals are estimated; validate the reference before scoring a song."]}
        return metadata, files
