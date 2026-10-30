"""Experimental pitch/rhythm/coverage scoring, not a trained singing judge."""

import hashlib
import json
import math
from pathlib import Path
from typing import Literal

import numpy as np
import soundfile as sf
from pydantic import BaseModel, ConfigDict, Field, model_validator

from services.karaoke.assets import canonical_json, sha256_file
from services.karaoke.audio import decode, inspect_wav
from services.karaoke.errors import ServiceError


EXTRACTOR_VERSION = "pyin-v1"
SCORING_VERSION = "pitch-rhythm-v3-30-20-50"
SAMPLE_RATE = 22050
HOP = 512
FRAME = 2048
MIN_SECONDS = 2.0
MAX_SCORE_SECONDS = 600
MAX_SCORE_FRAMES = math.ceil(MAX_SCORE_SECONDS * SAMPLE_RATE / HOP)


class Reference(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    schema_version: Literal[1] = 1
    extractor_version: Literal["pyin-v1"] = EXTRACTOR_VERSION
    reference_version: str = Field(pattern=r"^[a-f0-9]{64}$")
    audio_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    sample_rate: Literal[22050] = SAMPLE_RATE
    hop_length: Literal[512] = HOP
    duration_seconds: float = Field(gt=0, le=1800)
    f0_hz: list[float | None] = Field(min_length=1, max_length=80000)
    voiced_probability: list[float] = Field(min_length=1, max_length=80000)
    rms_dbfs: float = Field(ge=-240, le=6)
    clipped_fraction: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_frames(self):
        # Duration is stored as a float derived from an integer sample count.
        # At exact hop boundaries, binary float rounding can turn N into
        # N + epsilon and incorrectly demand one extra pYIN frame.
        expected = math.ceil(self.duration_seconds * SAMPLE_RATE / HOP - 1e-9)
        if len(self.f0_hz) != len(self.voiced_probability) or len(self.f0_hz) != expected:
            raise ValueError("Reference frame count does not match its timeline")
        if any(f is not None and not 60 <= f <= 1300 for f in self.f0_hz):
            raise ValueError("Reference pitch is out of range")
        if any(not 0 <= p <= 1 for p in self.voiced_probability):
            raise ValueError("Invalid voiced probability")
        payload = self.model_dump(exclude={"reference_version"})
        if hashlib.sha256(canonical_json(payload)).hexdigest() != self.reference_version:
            raise ValueError("Reference checksum mismatch")
        return self


class Timing(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    # Song time at recording sample zero. Negative means recording began earlier.
    recording_start_offset_ms: float = Field(default=0, ge=-30000, le=30000)
    # Positive means captured voice arrives this much later than the playback clock.
    capture_latency_ms: float = Field(default=0, ge=0, le=2000)
    allow_octave_shift: bool = True
    expected_reference_version: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class RecordingFeatures(BaseModel):
    """Bounded pitch features extracted incrementally by the browser."""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    duration_seconds: float = Field(gt=0, le=MAX_SCORE_SECONDS)
    f0_hz: list[float | None] = Field(min_length=1, max_length=MAX_SCORE_FRAMES)
    voiced_probability: list[float] = Field(min_length=1, max_length=MAX_SCORE_FRAMES)
    rms_dbfs: float = Field(ge=-240, le=6)
    clipped_fraction: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_frames(self):
        expected = math.ceil(self.duration_seconds * SAMPLE_RATE / HOP - 1e-9)
        if len(self.f0_hz) != len(self.voiced_probability) or len(self.f0_hz) != expected:
            raise ValueError("Recording feature frame count does not match its timeline")
        if any(f is not None and not 60 <= f <= 1300 for f in self.f0_hz):
            raise ValueError("Recording pitch is out of range")
        if any(not 0 <= p <= 1 for p in self.voiced_probability):
            raise ValueError("Invalid voiced probability")
        return self


def extract_pitch(wave: Path, max_seconds: int) -> dict:
    """Bound pYIN's Viterbi matrices by processing 15s windows with context."""
    import librosa
    info = inspect_wav(wave, max_seconds)
    if info["sample_rate"] != SAMPLE_RATE or info["channels"] != 1:
        raise ValueError("Pitch input must be canonical mono PCM")
    count = math.ceil(info["frames"] / HOP)
    pitches = np.full(count, np.nan, dtype=np.float64)
    probabilities = np.zeros(count, dtype=np.float64)
    frames_per_window = max(1, int(15 * SAMPLE_RATE / HOP))
    with sf.SoundFile(wave) as handle:
        for first in range(0, count, frames_per_window):
            last = min(count, first + frames_per_window)
            read_start = max(0, first * HOP - FRAME)
            read_end = min(info["frames"], last * HOP + FRAME)
            handle.seek(read_start)
            audio = handle.read(read_end - read_start, dtype="float32")
            if audio.size < FRAME:
                audio = np.pad(audio, (0, FRAME - audio.size))
            # Absolute silence must never become an artificially confident note.
            if float(np.sqrt(np.mean(audio.astype("float64") ** 2))) < 10 ** (-55 / 20):
                continue
            f0, voiced, probability = librosa.pyin(audio, fmin=65.0, fmax=1200.0, sr=SAMPLE_RATE,
                                                 frame_length=FRAME, hop_length=HOP, fill_na=np.nan)
            index = ((np.arange(first, last) * HOP - read_start) // HOP).astype(int)
            index = np.minimum(index, len(f0) - 1)
            for out_index, local in zip(range(first, last), index):
                center = int(local * HOP)
                clip = audio[max(0, center - FRAME // 2): min(len(audio), center + FRAME // 2)]
                rms = float(np.sqrt(np.mean(clip.astype("float64") ** 2))) if clip.size else 0
                if voiced[local] and np.isfinite(f0[local]) and rms >= 10 ** (-55 / 20):
                    pitches[out_index] = float(f0[local])
                    probabilities[out_index] = float(probability[local])
    return {"duration_seconds": info["duration_seconds"],
            "f0_hz": [float(f) if np.isfinite(f) else None for f in pitches],
            "voiced_probability": probabilities.tolist(),
            "rms_dbfs": info["rms_dbfs"], "clipped_fraction": info["clipped_fraction"]}


def build_reference(vocals: Path, work: Path, settings) -> Reference:
    canonical = work / "reference_audio.wav"
    decode(vocals, canonical, settings, sample_rate=SAMPLE_RATE, channels=1)
    payload = {"schema_version": 1, "extractor_version": EXTRACTOR_VERSION,
               "audio_sha256": sha256_file(vocals), "sample_rate": SAMPLE_RATE, "hop_length": HOP,
               **extract_pitch(canonical, settings.max_duration_seconds)}
    payload["reference_version"] = hashlib.sha256(canonical_json(payload)).hexdigest()
    return Reference.model_validate(payload)


def read_reference(path: Path, settings) -> Reference:
    if path.stat().st_size > settings.max_reference_bytes:
        raise ServiceError("REFERENCE_TOO_LARGE", "Reference exceeds its size budget", 413)
    try:
        reference = Reference.model_validate_json(path.read_bytes())
        if reference.duration_seconds > settings.max_duration_seconds:
            raise ValueError("Reference duration exceeds limit")
        return reference
    except (ValueError, TypeError, RecursionError) as exc:
        raise ServiceError("INVALID_REFERENCE", "Reference schema, checksum or version is invalid") from exc


def arrays(features: dict | Reference) -> tuple[np.ndarray, np.ndarray]:
    if isinstance(features, Reference):
        f0, confidence = features.f0_hz, features.voiced_probability
    else:
        f0, confidence = features["f0_hz"], features["voiced_probability"]
    pitch = np.array([x if x is not None else np.nan for x in f0], dtype=np.float64)
    active = np.isfinite(pitch) & (np.asarray(confidence) >= 0.5)
    return pitch, active


def reference_quality(reference: Reference) -> dict:
    _, active = arrays(reference)
    seconds = float(active.sum() * HOP / SAMPLE_RATE)
    sufficient = seconds >= MIN_SECONDS and reference.rms_dbfs >= -55 and reference.clipped_fraction < 0.1
    return {"status": "sufficient" if sufficient else "reference_unreliable",
            "voiced_seconds": round(seconds, 3),
            "warnings": ["Experimental monophonic reference; overlapping singers may be unreliable."]}


def events(pitch: np.ndarray, active: np.ndarray) -> np.ndarray:
    changes = np.flatnonzero(np.diff(np.r_[False, active, False].astype(int)))
    if len(pitch) > 1:
        with np.errstate(invalid="ignore", divide="ignore"):
            cents = np.abs(1200 * np.log2(pitch[1:] / pitch[:-1]))
        note_changes = np.flatnonzero(active[1:] & active[:-1] & (cents > 150)) + 1
        changes = np.unique(np.r_[changes, note_changes])
    selected = []
    for index in changes:
        if not selected or index - selected[-1] >= 3:
            selected.append(int(index))
    return np.asarray(selected, dtype=float) * HOP / SAMPLE_RATE


def rhythm_score(reference_events: np.ndarray, recording_events: np.ndarray) -> float:
    if not len(reference_events) or not len(recording_events):
        return 0.0
    candidates = []
    for i, t in enumerate(reference_events):
        left = int(np.searchsorted(recording_events, t - 0.15))
        right = int(np.searchsorted(recording_events, t + 0.15, side="right"))
        for j in range(left, right):
            candidates.append((abs(t - recording_events[j]), i, j))
    used_ref, used_rec, matched = set(), set(), 0.0
    for distance, i, j in sorted(candidates):
        if i not in used_ref and j not in used_rec:
            used_ref.add(i)
            used_rec.add(j)
            matched += max(0, 1 - distance / 0.15)
    return 100 * 2 * matched / (len(reference_events) + len(recording_events))


def overall_score(pitch: float, rhythm: float, coverage: float) -> float:
    return round(0.3 * pitch + 0.2 * rhythm + 0.5 * coverage, 2)


def score_features(reference: Reference, recording: dict, timing: Timing, request_id: str) -> dict:
    quality = reference_quality(reference)
    result = {"request_id": request_id, "status": "completed", "score": None,
              "quality": quality, "scoring_version": SCORING_VERSION,
              "reference_version": reference.reference_version}
    if timing.expected_reference_version and timing.expected_reference_version != reference.reference_version:
        raise ServiceError("REFERENCE_VERSION_MISMATCH", "The reference does not match the session")
    if quality["status"] != "sufficient":
        return result
    if recording["clipped_fraction"] >= 0.1:
        result["quality"] = {"status": "insufficient_audio", "warnings": ["Recording is heavily clipped."]}
        return result
    ref_pitch, ref_active = arrays(reference)
    rec_pitch, rec_active = arrays(recording)
    offset = (timing.recording_start_offset_ms - timing.capture_latency_ms) / 1000
    # Sampling in the fixed song timeline. Never stretch individual phrases to erase timing errors.
    positions = np.rint((np.arange(len(ref_pitch)) * HOP / SAMPLE_RATE - offset) * SAMPLE_RATE / HOP).astype(int)
    inside = (positions >= 0) & (positions < len(rec_pitch))
    mapped_pitch = np.full(len(ref_pitch), np.nan)
    mapped_active = np.zeros(len(ref_pitch), dtype=bool)
    mapped_pitch[inside] = rec_pitch[positions[inside]]
    mapped_active[inside] = rec_active[positions[inside]]
    paired = ref_active & mapped_active
    denominator = max(1, int(ref_active.sum()))
    coverage = 100 * paired.sum() / denominator
    octave = 0
    if paired.any():
        differences = 1200 * np.log2(mapped_pitch[paired] / ref_pitch[paired])
        choices = (-1200, 0, 1200) if timing.allow_octave_shift else (0,)
        octave = min(choices, key=lambda c: float(np.median(np.abs(differences - c))))
        # Missing expected voiced frames contribute zero, preventing a tiny perfect fragment from scoring highly.
        pitch = float(100 * np.exp(-((differences - octave) / 100) ** 2).sum() / denominator)
    else:
        pitch = 0.0
    rec_events = events(rec_pitch, rec_active) + offset
    ref_events = events(ref_pitch, ref_active)
    rhythm = rhythm_score(ref_events, rec_events)
    total = overall_score(pitch, rhythm, coverage)
    warnings = ["Experimental score; not a validated assessment of singing talent."]
    if not rec_active.any():
        warnings.append("No reliable singing detected; completion score is zero.")
    elif coverage < 50:
        warnings.append("Less than half of the expected singing was covered.")
    result["score"] = {"overall": total, "pitch": round(pitch, 2),
                       "rhythm": round(rhythm, 2), "coverage": round(float(coverage), 2)}
    result["quality"] = {"status": "sufficient", "warnings": warnings,
                         "applied_global_octave_shift_semitones": octave // 100}
    return result


def score_recording(recording: Path, reference_path: Path, work: Path, settings, timing: Timing, request_id: str) -> dict:
    reference = read_reference(reference_path, settings)
    canonical = work / "recording_audio.wav"
    decode(recording, canonical, settings, sample_rate=SAMPLE_RATE, channels=1)
    features = extract_pitch(canonical, settings.max_duration_seconds)
    return score_features(reference, features, timing, request_id)
