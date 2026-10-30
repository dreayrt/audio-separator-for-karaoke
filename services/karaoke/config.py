"""Runtime settings for the score-only API."""

import os
from dataclasses import dataclass
from pathlib import Path

PRODUCTION_HOST = os.environ.get("KARAOKE_PUBLIC_HOST", "https://moodify.click")
PRODUCTION_URL = os.environ.get("KARAOKE_API_URL", PRODUCTION_HOST + "/api/ai/karaoke")


def memory_ceiling(environment: str) -> int:
    if environment not in {"dev", "production", "test"}:
        raise ValueError("AI_ENV must be dev, production or test")
    return 100  # Legacy benchmark helper; no mandatory percentage policy.


@dataclass(frozen=True)
class Settings:
    api_key: str
    environment: str = "production"
    model_dir: Path = Path("/opt/models")
    temp_dir: Path = Path("/tmp/karaoke")
    cpu_threads: int = 1
    segment_size: int = 128
    overlap: int = 2
    chunk_seconds: int = 30
    max_request_bytes: int = 128 * 1024 * 1024
    max_reference_bytes: int = 4 * 1024 * 1024
    max_duration_seconds: int = 600
    max_temp_bytes: int = 1024 * 1024 * 1024
    command_timeout_seconds: int = 120
    memory_percent: int | None = None
    device: str | None = None
    gpu_memory_fraction: float = 0.85

    def __post_init__(self):
        if (len(self.api_key) < 24 or not self.api_key.isascii() or any(x.isspace() for x in self.api_key)
                or self.api_key.lower().startswith(("change", "example"))):
            raise ValueError("AI_API_KEY must contain at least 24 characters; use the launch command to generate it")
        memory_ceiling(self.environment)
        if self.device is None:
            object.__setattr__(self, "device", "cpu")
        if self.device != "cpu":
            raise ValueError("The score-only API uses CPU; GPU selection applies only to local preparation")
        if not 0 < self.gpu_memory_fraction <= 1:
            raise ValueError("AI_GPU_MEMORY_FRACTION must be greater than zero and at most one")
        if not 1 <= self.cpu_threads <= 64 or not 32 <= self.segment_size <= 512:
            raise ValueError("Invalid CPU thread/segment configuration")
        if not 1 <= self.overlap <= 8 or not 10 <= self.chunk_seconds <= 120:
            raise ValueError("Invalid overlap/chunk configuration")
        if self.memory_percent is not None and not 1 <= self.memory_percent <= 100:
            raise ValueError("Optional AI_MEMORY_PERCENT must be between 1 and 100")
        if not 1 <= self.max_duration_seconds <= 1800:
            raise ValueError("Audio duration must be between 1 and 1800 seconds")
        if not 1024 <= self.max_request_bytes <= 512 * 1024 * 1024:
            raise ValueError("Invalid request size limit")
        if not 1024 <= self.max_reference_bytes <= self.max_request_bytes:
            raise ValueError("Invalid reference size limit")
        if self.max_temp_bytes < self.max_request_bytes or self.command_timeout_seconds < 1:
            raise ValueError("Invalid temporary disk/command limits")

    @classmethod
    def from_env(cls):
        def integer(name, default):
            return int(os.environ.get(name, default))
        return cls(
            api_key=os.environ.get("AI_API_KEY", ""),
            environment=os.environ.get("AI_ENV", "production"),
            model_dir=Path(os.environ.get("AI_MODEL_DIR", "/opt/models")),
            temp_dir=Path(os.environ.get("AI_TEMP_DIR", "/tmp/karaoke")),
            cpu_threads=integer("AI_CPU_THREADS", 1),
            segment_size=integer("AI_SEGMENT_SIZE", 128),
            overlap=integer("AI_OVERLAP", 2),
            chunk_seconds=integer("AI_CHUNK_SECONDS", 30),
            max_request_bytes=integer("AI_MAX_REQUEST_BYTES", 128 * 1024 * 1024),
            max_reference_bytes=integer("AI_MAX_REFERENCE_BYTES", 4 * 1024 * 1024),
            max_duration_seconds=integer("AI_MAX_DURATION_SECONDS", 600),
            max_temp_bytes=integer("AI_MAX_TEMP_BYTES", 1024 * 1024 * 1024),
            command_timeout_seconds=integer("AI_COMMAND_TIMEOUT_SECONDS", 120),
            memory_percent=int(os.environ["AI_MEMORY_PERCENT"]) if os.environ.get("AI_MEMORY_PERCENT") else None,
            device=os.environ.get("AI_DEVICE") or None,
            gpu_memory_fraction=float(os.environ.get("AI_GPU_MEMORY_FRACTION", ".85")),
        )
