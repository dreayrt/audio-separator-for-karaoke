"""Create word-level karaoke timings by forced-aligning lyrics to the vocal stem.

This is an offline preparation command. It does not alter audio files. By default it
exports alignment metadata to JSON; pass --write-mongodb to add the metadata to the
existing karaoke_assets documents in the selected MongoDB database.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
import unicodedata
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import numpy as np
import soundfile as sf
import torch
import torchaudio.functional as audio_functional
from pymongo import MongoClient
from transformers import AutoFeatureExtractor, AutoModelForCTC, AutoTokenizer


DEFAULT_MODEL = "nguyenvulebinh/wav2vec2-base-vi-vlsp2020"
TARGET_SAMPLE_RATE = 16_000


def normalize_words(raw: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", raw).lower()
    output: list[str] = []
    current: list[str] = []
    for char in normalized:
        category = unicodedata.category(char)
        if char.isalnum() or category.startswith("M"):
            current.append(char)
        elif current:
            output.append("".join(current))
            current.clear()
    if current:
        output.append("".join(current))
    return output


def lyrics_lines(track: dict[str, Any]) -> list[dict[str, Any]]:
    synced = str(track.get("lyrics_synced") or "")
    raw = synced if re.search(r"\[\d{1,2}:\d{2}(?:\.\d{1,3})?\]", synced) else (track.get("lyrics_plain") or synced)
    result: list[dict[str, Any]] = []
    lrc_tag = re.compile(r"\[(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\]")
    for line in str(raw).splitlines():
        line = line.strip()
        if not line or re.match(r"^\[(ti|ar|al|by|offset|length):", line, re.I):
            continue
        tags = list(lrc_tag.finditer(line))
        start_hints: list[int | None] = [None]
        if tags:
            line = line[tags[-1].end():].strip()
            start_hints = []
            for tag in tags:
                fractional = tag.group(3) or "0"
                start_hints.append(round((int(tag.group(1)) * 60 + int(tag.group(2)) + float("0." + fractional)) * 1000))
        words = normalize_words(line)
        if words:
            for start_hint in start_hints:
                result.append({"text": " ".join(words), "words": words, "startHintMs": start_hint})
    if result and all(line["startHintMs"] is not None for line in result):
        result.sort(key=lambda line: line["startHintMs"])
    return result


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_vocals(asset: dict[str, Any], destination: Path) -> None:
    assets = asset.get("assets") or {}
    vocals = assets.get("vocals") or {}
    key = vocals.get("storageKey")
    storage = asset.get("storage") or {}
    base_url = storage.get("baseUrl") or "https://moodify.click/"
    if not key:
        raise ValueError("karaoke_assets document has no vocals storageKey")
    url = urljoin(base_url.rstrip("/") + "/", str(key).lstrip("/"))
    request = urllib.request.Request(url, headers={"User-Agent": "MoodifyLyricAligner/1.0"})
    with urllib.request.urlopen(request, timeout=90) as response, destination.open("wb") as output:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            output.write(chunk)


def load_audio(path: Path, device: torch.device) -> tuple[torch.Tensor, float]:
    audio, sample_rate = sf.read(path, dtype="float32", always_2d=True)
    mono = torch.from_numpy(np.ascontiguousarray(audio.mean(axis=1)))
    if sample_rate != TARGET_SAMPLE_RATE:
        mono = audio_functional.resample(mono, sample_rate, TARGET_SAMPLE_RATE)
    duration = mono.numel() / TARGET_SAMPLE_RATE
    return mono.to(device), duration


def token_word_groups(tokenizer: Any, word_texts: list[str]) -> tuple[list[int], list[int]]:
    delimiter = tokenizer.word_delimiter_token
    if not delimiter:
        raise ValueError("The selected CTC tokenizer has no word delimiter token")
    delimiter_id = tokenizer.convert_tokens_to_ids(delimiter)
    ids: list[int] = []
    token_to_word: list[int] = []
    word_index = 0
    for index, word_text in enumerate(word_texts):
        encoded = tokenizer.encode(word_text, add_special_tokens=False)
        if not encoded:
            continue
        ids.extend(encoded)
        token_to_word.extend([word_index] * len(encoded))
        word_index += 1
        if index < len(word_texts) - 1:
            ids.append(delimiter_id)
            token_to_word.append(-1)
    if word_index != len(word_texts):
        raise ValueError("Some lyric words could not be encoded by the selected model")
    if tokenizer.unk_token_id is not None and tokenizer.unk_token_id in ids:
        raise ValueError("Lyrics contain characters not supported by the selected alignment model")
    return ids, token_to_word


def align_token_sequence(
    log_probs: torch.Tensor,
    target_ids: list[int],
    blank_id: int,
    frame_offset: int = 0,
) -> list[tuple[int, int, float]]:
    if not target_ids or len(target_ids) > log_probs.shape[1]:
        raise ValueError("Lyrics are longer than the vocal audio segment can align")
    targets = torch.tensor([target_ids], dtype=torch.int32, device=log_probs.device)
    paths, frame_scores = audio_functional.forced_align(
        log_probs,
        targets,
        input_lengths=torch.tensor([log_probs.shape[1]], dtype=torch.int32, device=log_probs.device),
        target_lengths=torch.tensor([len(target_ids)], dtype=torch.int32, device=log_probs.device),
        blank=blank_id,
    )
    path = paths[0].tolist()
    scores = frame_scores[0].tolist()
    spans: list[tuple[int, int, float]] = []
    cursor = 0
    for token_id in target_ids:
        while cursor < len(path) and path[cursor] != token_id:
            cursor += 1
        if cursor >= len(path):
            raise ValueError("Forced alignment could not match every lyric character")
        start = cursor
        while cursor < len(path) and path[cursor] == token_id:
            cursor += 1
        end = cursor
        score = float(np.mean(scores[start:end])) if end > start else -20.0
        spans.append((start + frame_offset, end + frame_offset, score))
    return spans


def word_events(
    words: list[dict[str, Any]],
    token_to_word: list[int],
    token_spans: list[tuple[int, int, float]],
    frame_seconds: float,
    duration_ms: int,
    line_index: int,
) -> list[dict[str, Any]]:
    per_word: list[list[tuple[int, int, float]]] = [[] for _ in words]
    for span, word_index in zip(token_spans, token_to_word):
        if word_index >= 0:
            per_word[word_index].append(span)
    result: list[dict[str, Any]] = []
    for word, spans in zip(words, per_word):
        if not spans:
            continue
        start_frame = min(span[0] for span in spans)
        end_frame = max(span[1] for span in spans)
        confidence = float(np.mean([np.exp(span[2]) for span in spans]))
        start_ms = max(0, round(start_frame * frame_seconds * 1000))
        end_ms = min(duration_ms, max(start_ms + 1, round(end_frame * frame_seconds * 1000)))
        result.append({
            "text": word["text"],
            "startMs": start_ms,
            "endMs": end_ms,
            "lineIndex": line_index,
            "confidence": round(confidence, 4),
        })
    return result


def align_track(
    track: dict[str, Any],
    asset: dict[str, Any],
    feature_extractor: Any,
    tokenizer: Any,
    model: Any,
    device: torch.device,
    model_id: str,
    confidence_threshold: float,
) -> dict[str, Any]:
    lines = lyrics_lines(track)
    if not lines:
        raise ValueError("Track has no usable lyrics")
    words = [word for line in lines for word in line["words"]]

    guided_by_lrc = all(line["startHintMs"] is not None for line in lines)

    with tempfile.TemporaryDirectory(prefix="moodify-lyric-align-") as temp_dir:
        vocal_path = Path(temp_dir) / "vocals.wav"
        download_vocals(asset, vocal_path)
        audio, duration = load_audio(vocal_path, device)
        inputs = feature_extractor(audio.detach().cpu().numpy(), sampling_rate=TARGET_SAMPLE_RATE, return_tensors="pt")
        input_values = inputs.input_values.to(device)
        with torch.inference_mode():
            logits = model(input_values).logits
            log_probs = logits.log_softmax(dim=-1)

        frame_seconds = duration / log_probs.shape[1]
        duration_ms = round(duration * 1000)
        aligned_words: list[dict[str, Any]] = []
        if guided_by_lrc:
            for line_index, line in enumerate(lines):
                line_words = [{"text": word} for word in line["words"]]
                target_ids, token_to_word = token_word_groups(tokenizer, [word["text"] for word in line_words])
                line_start_ms = int(line["startHintMs"])
                line_end_ms = int(lines[line_index + 1]["startHintMs"]) if line_index + 1 < len(lines) else duration_ms
                if line_end_ms <= line_start_ms:
                    raise ValueError("LRC lyric timestamps are not in increasing order")
                first_frame = max(0, round((line_start_ms - 120) / 1000 / frame_seconds))
                last_frame = min(log_probs.shape[1], max(first_frame + 1, round(line_end_ms / 1000 / frame_seconds)))
                token_spans = align_token_sequence(log_probs[:, first_frame:last_frame, :], target_ids,
                                                   tokenizer.pad_token_id, first_frame)
                aligned_words.extend(word_events(line_words, token_to_word, token_spans,
                                                 frame_seconds, duration_ms, line_index))
        else:
            all_words: list[dict[str, Any]] = []
            for line_index, line in enumerate(lines):
                all_words.extend({"text": word, "lineIndex": line_index} for word in line["words"])
            target_ids, token_to_word = token_word_groups(tokenizer, [word["text"] for word in all_words])
            token_spans = align_token_sequence(log_probs, target_ids, tokenizer.pad_token_id)
            for line_index in range(len(lines)):
                line_words = [word for word in all_words if word["lineIndex"] == line_index]
                word_start = sum(len(line["words"]) for line in lines[:line_index])
                word_end = word_start + len(line_words)
                selected = [(span, word_index - word_start) for span, word_index in zip(token_spans, token_to_word)
                            if word_start <= word_index < word_end]
                line_spans = [span for span, _ in selected]
                line_map = [word_index for _, word_index in selected]
                aligned_words.extend(word_events(line_words, line_map, line_spans,
                                                 frame_seconds, duration_ms, line_index))

        mean_confidence = float(np.mean([word["confidence"] for word in aligned_words])) if aligned_words else 0.0
        coverage = len(aligned_words) / len(words)
        aligned_lines: list[dict[str, Any]] = []
        for line_index, line in enumerate(lines):
            line_words = [word for word in aligned_words if word["lineIndex"] == line_index]
            if line_words:
                aligned_lines.append({
                    "text": line["text"],
                    "startMs": line_words[0]["startMs"],
                    "endMs": line_words[-1]["endMs"],
                    "firstWordIndex": aligned_words.index(line_words[0]),
                    "wordCount": len(line_words),
                })

        digest = file_sha256(vocal_path)
        timeline_status = "ready" if guided_by_lrc and coverage == 1.0 and mean_confidence >= confidence_threshold else "needs_review"
        return {
            "version": 1,
            "status": timeline_status,
            "language": "vi",
            "method": "ctc_forced_alignment",
            "model": model_id,
            "anchoredByLrc": guided_by_lrc,
            "sampleRate": TARGET_SAMPLE_RATE,
            "audioSha256": digest,
            "textSha256": hashlib.sha256("\n".join(line["text"] for line in lines).encode("utf-8")).hexdigest(),
            "durationMs": round(duration * 1000),
            "coverage": round(coverage, 4),
            "meanConfidence": round(mean_confidence, 4),
            "words": aligned_words,
            "lines": aligned_lines,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default="music_streaming_1")
    parser.add_argument("--mongo-uri", default="mongodb://127.0.0.1:27017")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--song-id", action="append", dest="song_ids", help="Limit to this song ID; may be repeated")
    parser.add_argument("--limit", type=int, help="Limit the number of tracks, useful for a pilot run")
    parser.add_argument("--min-confidence", type=float, default=0.08)
    parser.add_argument("--write-mongodb", action="store_true", help="Write timelines to existing karaoke_assets documents")
    parser.add_argument("--output", type=Path, default=Path("lyric-timings.json"))
    args = parser.parse_args()

    client = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=5000)
    database = client[args.database]
    assets = list(database.karaoke_assets.find({"status": "ready"}).sort("songId", 1))
    if args.song_ids:
        wanted = set(args.song_ids)
        assets = [asset for asset in assets if asset.get("songId") in wanted]
    if args.limit is not None:
        assets = assets[:max(0, args.limit)]
    if not assets:
        print("No ready karaoke assets found in the selected database.", file=sys.stderr)
        return 2

    from bson import ObjectId

    tracks: dict[str, dict[str, Any]] = {}
    for asset in assets:
        song_id = str(asset.get("songId", ""))
        if not ObjectId.is_valid(song_id):
            continue
        track = database.tracks.find_one({"_id": ObjectId(song_id)}, {"lyrics_plain": 1, "lyrics_synced": 1, "name": 1})
        if track:
            tracks[song_id] = track
    assets = [asset for asset in assets if str(asset.get("songId")) in tracks]
    if not assets:
        print("No ready karaoke assets matched a track document with lyrics.", file=sys.stderr)
        return 2

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Loading {args.model} on {device}; aligning {len(assets)} song(s).", flush=True)
    feature_extractor = AutoFeatureExtractor.from_pretrained(args.model)
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForCTC.from_pretrained(args.model).to(device).eval()

    results: list[dict[str, Any]] = []
    for index, asset in enumerate(assets, start=1):
        song_id = str(asset["songId"])
        track = tracks[song_id]
        try:
            timeline = align_track(track, asset, feature_extractor, tokenizer, model, device, args.model, args.min_confidence)
            result = {"songId": song_id, "assetVersion": asset.get("assetVersion"), "title": track.get("name"), "lyricTimeline": timeline}
            if args.write_mongodb:
                update = database.karaoke_assets.update_one(
                    {"songId": song_id, "assetVersion": asset.get("assetVersion"), "status": "ready"},
                    {"$set": {"lyricTimeline": timeline}},
                )
                if update.matched_count != 1:
                    raise RuntimeError("Asset version changed before timeline could be saved")
            results.append(result)
            print(f"[{index}/{len(assets)}] {song_id}: {timeline['status']}, {len(timeline['words'])} words, confidence={timeline['meanConfidence']:.3f}", flush=True)
        except Exception as error:  # Keep the batch moving and report only the affected song/error.
            results.append({"songId": song_id, "assetVersion": asset.get("assetVersion"), "title": track.get("name"), "error": str(error)})
            print(f"[{index}/{len(assets)}] {song_id}: alignment failed: {error}", file=sys.stderr, flush=True)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {len(results)} result(s) to {args.output.resolve()}")
    return 0 if any("lyricTimeline" in result for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
