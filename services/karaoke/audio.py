"""Bounded, local-file-only decoding. User filenames are never used as paths."""

import json
import math
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

from services.karaoke.errors import ServiceError

FORMATS = "wav,flac,mp3,ogg,mov,matroska,webm,aiff,ac3,aac"


def command(arguments: list[str], timeout: int) -> bytes:
    try:
        result = subprocess.run(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=timeout, check=False)
    except FileNotFoundError as exc:
        raise ServiceError("AUDIO_RUNTIME_MISSING", "FFmpeg/ffprobe is not installed", 503) from exc
    except subprocess.TimeoutExpired as exc:
        raise ServiceError("AUDIO_DECODE_TIMEOUT", "Audio decoding exceeded its time budget") from exc
    if result.returncode:
        raise ServiceError("INVALID_AUDIO", "The uploaded file could not be decoded as audio")
    return result.stdout


def decode(source: Path, target: Path, settings, *, sample_rate: int = 44100, channels: int = 2) -> dict:
    raw = command(["ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe", "-format_whitelist", FORMATS, "-select_streams", "a:0",
                   "-show_entries", "stream=codec_type,sample_rate,channels:format=duration", "-of", "json", str(source)],
                  settings.command_timeout_seconds)
    try:
        data = json.loads(raw)
        streams = data.get("streams", [])
        if not streams or not 1 <= int(streams[0].get("channels", 0)) <= 8:
            raise ValueError("Unsupported audio stream")
        duration = float(data.get("format", {}).get("duration", 0))
        if not math.isfinite(duration) or duration < 0:
            raise ValueError("Invalid duration")
    except (ValueError, TypeError, KeyError) as exc:
        raise ServiceError("INVALID_AUDIO", "Invalid audio stream metadata") from exc
    if duration > settings.max_duration_seconds + 0.05:
        raise ServiceError("AUDIO_TOO_LONG", "Audio exceeds the configured duration limit")
    command(["ffmpeg", "-nostdin", "-v", "error", "-y", "-protocol_whitelist", "file,pipe", "-format_whitelist", FORMATS, "-threads", "1",
             "-i", str(source), "-map", "0:a:0", "-vn", "-t", str(settings.max_duration_seconds + 1),
             "-ar", str(sample_rate), "-ac", str(channels), "-c:a", "pcm_s16le", "-threads", "1", str(target)],
            settings.command_timeout_seconds)
    return inspect_wav(target, settings.max_duration_seconds)


def inspect_wav(path: Path, max_seconds: int) -> dict:
    try:
        info = sf.info(path)
        if not info.frames or info.samplerate <= 0 or info.channels not in (1, 2):
            raise ValueError("Invalid waveform")
        duration = info.frames / info.samplerate
        if duration > max_seconds + 0.001:
            raise ServiceError("AUDIO_TOO_LONG", "Decoded audio exceeds the duration limit")
        peak = 0.0
        squares = 0.0
        clipped = 0
        count = 0
        for block in sf.blocks(path, blocksize=65536, dtype="float32", always_2d=True):
            if not np.isfinite(block).all():
                raise ValueError("Non-finite samples")
            peak = max(peak, float(np.max(np.abs(block))))
            squares += float(np.sum(block.astype("float64") ** 2))
            clipped += int(np.sum(np.abs(block) >= 0.999))
            count += block.size
        return {"frames": info.frames, "sample_rate": info.samplerate, "channels": info.channels,
                "duration_seconds": duration, "peak": peak,
                "rms_dbfs": 20 * math.log10(max(math.sqrt(squares / max(count, 1)), 1e-12)),
                "clipped_fraction": clipped / max(count, 1)}
    except ServiceError:
        raise
    except (OSError, ValueError, RuntimeError) as exc:
        raise ServiceError("INVALID_AUDIO", "Invalid or unreadable waveform") from exc
