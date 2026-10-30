import hashlib
import math

import numpy as np
import pytest
import soundfile as sf

from services.karaoke.assets import canonical_json
from services.karaoke.errors import ServiceError
from services.karaoke.scoring import (
    HOP, SAMPLE_RATE, RecordingFeatures, Reference, Timing, extract_pitch,
    overall_score, score_features,
)


def reference(duration=8.0, pitch=220.0):
    count = math.ceil(duration * SAMPLE_RATE / HOP)
    data = {"schema_version": 1, "extractor_version": "pyin-v1", "audio_sha256": "a" * 64,
            "sample_rate": SAMPLE_RATE, "hop_length": HOP, "duration_seconds": duration,
            "f0_hz": [pitch] * count, "voiced_probability": [1.0] * count,
            "rms_dbfs": -20.0, "clipped_fraction": 0.0}
    data["reference_version"] = hashlib.sha256(canonical_json(data)).hexdigest()
    return Reference.model_validate(data)


def recording(ref, pitch=220.0):
    return {"duration_seconds": ref.duration_seconds, "f0_hz": [pitch] * len(ref.f0_hz),
            "voiced_probability": [1.0] * len(ref.f0_hz), "rms_dbfs": -20.0, "clipped_fraction": 0.0}


def test_matching_pitch_scores_higher_than_detuned_singing():
    ref = reference()
    good = score_features(ref, recording(ref), Timing(), "same")
    bad = score_features(ref, recording(ref, pitch=277.18), Timing(), "wrong-notes")
    assert good["score"]["overall"] == 100
    assert bad["score"]["overall"] < 55


def test_overall_uses_30_20_50_weights():
    assert overall_score(80, 60, 40) == 56


def test_incremental_recording_features_validate_timeline():
    valid = RecordingFeatures(
        duration_seconds=1,
        f0_hz=[None] * math.ceil(SAMPLE_RATE / HOP),
        voiced_probability=[0] * math.ceil(SAMPLE_RATE / HOP),
        rms_dbfs=-20,
        clipped_fraction=0,
    )
    assert len(valid.f0_hz) == 44
    with pytest.raises(ValueError, match="frame count"):
        RecordingFeatures(
            duration_seconds=1,
            f0_hz=[None] * 43,
            voiced_probability=[0] * 43,
            rms_dbfs=-20,
            clipped_fraction=0,
        )


def test_missing_most_of_song_cannot_get_a_high_score():
    ref = reference()
    rec = recording(ref)
    cut = len(rec["f0_hz"]) // 4
    rec["f0_hz"][cut:] = [None] * (len(rec["f0_hz"]) - cut)
    rec["voiced_probability"][cut:] = [0.0] * (len(rec["f0_hz"]) - cut)
    result = score_features(ref, rec, Timing(), "fragment")
    assert result["score"]["coverage"] < 26
    assert result["score"]["overall"] < 40


def test_valid_silence_gets_zero_not_a_fabricated_pitch_score():
    ref = reference()
    rec = recording(ref)
    rec.update(f0_hz=[None] * len(ref.f0_hz), voiced_probability=[0.0] * len(ref.f0_hz), rms_dbfs=-240.0)
    result = score_features(ref, rec, Timing(), "silent")
    assert result["score"] == {"overall": 0, "pitch": 0, "rhythm": 0, "coverage": 0}


def test_global_octave_policy_is_explicit():
    ref = reference()
    rec = recording(ref, pitch=440.0)
    tolerant = score_features(ref, rec, Timing(allow_octave_shift=True), "octave")
    strict = score_features(ref, rec, Timing(allow_octave_shift=False), "octave")
    assert tolerant["score"]["overall"] == 100
    assert tolerant["quality"]["applied_global_octave_shift_semitones"] == 12
    assert strict["score"]["overall"] < 55


def test_timing_errors_are_not_freely_warped_away():
    ref = reference()
    rec = recording(ref)
    result = score_features(ref, rec, Timing(recording_start_offset_ms=500), "late")
    assert result["score"]["rhythm"] < 60
    assert result["score"]["coverage"] < 95


def test_reference_mismatch_and_corruption_rejected():
    ref = reference()
    with pytest.raises(ServiceError, match="does not match"):
        score_features(ref, recording(ref), Timing(expected_reference_version="b" * 64), "wrong-reference")
    corrupt = ref.model_dump()
    corrupt["f0_hz"][0] = 330.0
    with pytest.raises(ValueError, match="checksum"):
        Reference.model_validate(corrupt)


def test_invalid_frame_count_or_nonfinite_values_rejected():
    ref = reference().model_dump()
    ref["f0_hz"].append(220.0)
    with pytest.raises(ValueError):
        Reference.model_validate(ref)
    ref = reference().model_dump()
    ref["duration_seconds"] = float("nan")
    with pytest.raises(ValueError):
        Reference.model_validate(ref)


def test_unreliable_reference_or_heavily_clipped_recording_has_no_score():
    short = reference(duration=0.5)
    assert score_features(short, recording(short), Timing(), "short")["score"] is None
    ref = reference()
    rec = recording(ref)
    rec["clipped_fraction"] = 0.5
    assert score_features(ref, rec, Timing(), "clipped")["quality"]["status"] == "insufficient_audio"


def test_real_pyin_extracts_a_known_sine_and_ignores_silence(tmp_path):
    wave = tmp_path / "sine.wav"
    samples = np.arange(SAMPLE_RATE * 3) / SAMPLE_RATE
    sf.write(wave, 0.25 * np.sin(2 * np.pi * 220 * samples), SAMPLE_RATE)
    features = extract_pitch(wave, 10)
    pitches = [f for f in features["f0_hz"] if f is not None]
    assert len(pitches) > len(features["f0_hz"]) * 0.8
    assert abs(float(np.median(pitches)) - 220) < 3
    sf.write(wave, np.zeros(SAMPLE_RATE * 3), SAMPLE_RATE)
    silent = extract_pitch(wave, 10)
    assert all(f is None for f in silent["f0_hz"])
