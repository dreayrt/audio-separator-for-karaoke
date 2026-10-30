"""Prepare karaoke stems and a pitch-reference manifest on the local machine."""

import argparse
from datetime import datetime, timezone
import gc
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
from types import SimpleNamespace
import uuid


def available_cpu_threads() -> int:
    try:
        count = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        count = os.cpu_count() or 1
    return max(1, min(64, count))


def configure_thread_environment(threads: int) -> None:
    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMBA_NUM_THREADS"):
        os.environ[name] = str(threads)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run once before a song is published. Uses CUDA automatically when available, otherwise all available CPU threads."
    )
    parser.add_argument("--input", type=Path, required=True, help="Original local audio file")
    parser.add_argument("--song-id", required=True, help="Song ID used by the backend/MongoDB document")
    parser.add_argument("--output-dir", type=Path, required=True,
                        help="New directory for stems, pitch reference and upload manifest")
    parser.add_argument("--model-dir", type=Path,
                        default=Path(os.environ.get("AI_MODEL_DIR", ".karaoke-models")),
                        help="Verified local model bundle directory")
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto",
                        help="Default auto selects CUDA if visible, otherwise CPU")
    parser.add_argument("--cpu-threads", default="auto",
                        help="CPU threads used by PyTorch; default auto uses every available thread")
    parser.add_argument("--gpu-memory-fraction", type=float, default=0.90,
                        help="Maximum share of GPU VRAM this run may allocate; default leaves desktop headroom")
    parser.add_argument("--segment-size", type=int, default=128)
    parser.add_argument("--overlap", type=int, default=2)
    parser.add_argument("--chunk-seconds", type=int, default=30,
                        help="Larger chunks can improve throughput but use more RAM/VRAM")
    parser.add_argument("--max-duration-seconds", type=int, default=1800)
    return parser.parse_args()


def describe_asset(path: Path, **metadata) -> dict:
    from services.karaoke.assets import sha256_file

    return {"file": path.name, "sha256": sha256_file(path), "bytes": path.stat().st_size, **metadata}


def main() -> None:
    args = parse_args()
    source = args.input.expanduser().resolve()
    output = args.output_dir.expanduser().resolve()
    model_dir = args.model_dir.expanduser().resolve()
    if not source.is_file():
        raise SystemExit(f"Input audio does not exist: {source}")
    if not args.song_id.strip() or len(args.song_id) > 256:
        raise SystemExit("--song-id must contain 1 to 256 characters")
    if output.exists():
        raise SystemExit(f"Output directory already exists; choose a new path: {output}")
    if not 0.05 <= args.gpu_memory_fraction <= 1:
        raise SystemExit("--gpu-memory-fraction must be between 0.05 and 1")
    if not 32 <= args.segment_size <= 512 or not 1 <= args.overlap <= 8:
        raise SystemExit("Invalid model segment/overlap settings")
    if not 10 <= args.chunk_seconds <= 120 or not 1 <= args.max_duration_seconds <= 1800:
        raise SystemExit("Invalid chunk or duration limit")
    try:
        threads = available_cpu_threads() if args.cpu_threads == "auto" else int(args.cpu_threads)
    except ValueError as exc:
        raise SystemExit("--cpu-threads must be 'auto' or an integer") from exc
    if not 1 <= threads <= available_cpu_threads():
        raise SystemExit(f"--cpu-threads must be between 1 and {available_cpu_threads()}")

    # Set thread pools before importing PyTorch, NumPy, librosa or the separator package.
    configure_thread_environment(threads)
    try:
        import psutil
        import torch
    except ImportError as exc:
        raise SystemExit("Preparation dependencies are missing; use the karaoke preprocessor image or install its pinned dependencies") from exc

    cuda_available = bool(torch.cuda.is_available())
    if args.device == "cuda" and not cuda_available:
        raise SystemExit("CUDA was requested but is not visible. Expose an NVIDIA GPU to Docker or use --device cpu.")
    device = "cuda" if args.device == "cuda" or (args.device == "auto" and cuda_available) else "cpu"
    gpu_fraction = args.gpu_memory_fraction
    gpu_free_bytes = gpu_total_bytes = None
    if device == "cuda":
        gpu_free_bytes, gpu_total_bytes = torch.cuda.mem_get_info(0)
        # Scale the allocator ceiling to currently free VRAM and keep a small margin for display/other processes.
        gpu_fraction = min(gpu_fraction, (gpu_free_bytes / gpu_total_bytes) * 0.95)
        if gpu_fraction < 0.05:
            raise SystemExit("Too little free GPU memory is available; close other GPU tasks or run with --device cpu.")
    torch.set_num_threads(threads)
    try:
        torch.set_num_interop_threads(1)
    except RuntimeError:
        pass

    try:
        import soundfile as sf
        from services.karaoke.assets import PROFILE, sha256_file
        from services.karaoke.engine import SeparationEngine
        from services.karaoke.scoring import EXTRACTOR_VERSION, build_reference, reference_quality
    except ImportError as exc:
        raise SystemExit("Preparation dependencies are missing; use the karaoke preprocessor image or install its pinned dependencies") from exc

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.prepare-", dir=output.parent))
    work = temporary / "work"
    work.mkdir()
    staged = temporary / "assets"
    staged.mkdir()
    settings = SimpleNamespace(
        environment="local", device=device, gpu_memory_fraction=gpu_fraction,
        cpu_threads=threads, segment_size=args.segment_size, overlap=args.overlap,
        chunk_seconds=args.chunk_seconds, model_dir=model_dir, temp_dir=work,
        max_duration_seconds=args.max_duration_seconds, command_timeout_seconds=1800,
        max_reference_bytes=64 * 1024 * 1024,
    )

    try:
        if not model_dir.is_dir():
            raise SystemExit(f"Verified model bundle not found at {model_dir}; prepare it with services.karaoke.tools.prepare_model first")
        memory = psutil.virtual_memory()
        if device == "cuda":
            print(f"Device: {torch.cuda.get_device_name(0)}; free VRAM: {gpu_free_bytes / 1024**3:.2f} / {gpu_total_bytes / 1024**3:.2f} GiB", flush=True)
        else:
            print(f"Device: CPU; threads: {threads}; available RAM: {memory.available / 1024**3:.2f} GiB", flush=True)
        print(f"Preparing song {args.song_id!r}; this command runs in the foreground until the files are ready.", flush=True)

        started = time.perf_counter()
        load_started = time.perf_counter()
        engine = SeparationEngine(settings)
        model_load_seconds = time.perf_counter() - load_started
        request_id = uuid.uuid4().hex
        separation_started = time.perf_counter()
        metadata, separated = engine.separate(source, work, request_id)
        separation_seconds = time.perf_counter() - separation_started
        for name in ("instrumental", "vocals"):
            destination = staged / f"{name}.wav"
            shutil.copy2(separated[name], destination)
        engine_info = engine.info()
        del engine
        gc.collect()
        if device == "cuda":
            torch.cuda.empty_cache()
        reference_started = time.perf_counter()
        reference = build_reference(staged / "vocals.wav", work, settings)
        reference_seconds = time.perf_counter() - reference_started
        reference_path = staged / "pitch_reference.json"
        reference_path.write_text(reference.model_dump_json(), encoding="utf-8")
        quality = reference_quality(reference)

        source_info = metadata["duration_seconds"], metadata["sample_rate"]
        instrumental_info = sf.info(staged / "instrumental.wav")
        vocals_info = sf.info(staged / "vocals.wav")
        if (instrumental_info.frames != vocals_info.frames
                or instrumental_info.samplerate != vocals_info.samplerate
                or abs(instrumental_info.frames / instrumental_info.samplerate - source_info[0]) > 2 / source_info[1]):
            raise RuntimeError("Prepared stems do not match the original song timeline")

        manifest = {
            "schemaVersion": 1,
            "collection": "karaoke_assets",
            "songId": args.song_id,
            "status": "prepared_local",
            "source": {"filename": source.name, "sha256": sha256_file(source),
                       "durationSeconds": source_info[0], "sampleRate": source_info[1]},
            "assets": {
                "instrumental": describe_asset(staged / "instrumental.wav", format="wav",
                                               sampleRate=instrumental_info.samplerate,
                                               channels=instrumental_info.channels,
                                               durationSeconds=instrumental_info.frames / instrumental_info.samplerate),
                "vocals": describe_asset(staged / "vocals.wav", format="wav",
                                         sampleRate=vocals_info.samplerate, channels=vocals_info.channels,
                                         durationSeconds=vocals_info.frames / vocals_info.samplerate),
                "pitchReference": describe_asset(
                    reference_path, format="json", referenceVersion=reference.reference_version,
                    extractorVersion=EXTRACTOR_VERSION, sampleRate=reference.sample_rate,
                    hopLength=reference.hop_length),
            },
            "scoringReference": {"status": quality["status"], "voicedSeconds": quality["voiced_seconds"],
                                 "warnings": quality["warnings"]},
            "processing": {
                "profile": PROFILE,
                "modelFilename": engine_info["model_filename"],
                "modelVersion": engine_info["model_version"],
                "configVersion": engine_info["config_version"],
                "device": engine_info["device"],
                "deviceName": engine_info["device_name"],
                "precision": engine_info["parameters"]["precision"],
                "cpuThreads": threads,
                "gpuMemoryFraction": engine_info["gpu_memory_fraction"],
                "parameters": engine_info["parameters"],
                "modelLoadSeconds": round(model_load_seconds, 3),
                "separationSeconds": round(separation_seconds, 3),
                "referenceSeconds": round(reference_seconds, 3),
                "totalSeconds": round(time.perf_counter() - started, 3),
                "preparedAt": datetime.now(timezone.utc).isoformat(),
            },
            "backendNotes": {
                "fileReferences": "Upload the assets to the Google Cloud VM under /srv/moodify/karaoke/{songId}/{assetVersion}/, then use their storage keys when writing the karaoke_assets document.",
                "lyrics": "The separator produces a vocals audio stem, not lyric text. Reuse the existing song lyrics and timing data in the backend.",
            },
        }
        (staged / "karaoke_asset_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        os.replace(staged, output)
        print(json.dumps({"status": "prepared", "songId": args.song_id, "output": str(output),
                          "device": engine_info["device_name"], "cpuThreads": threads,
                          "durationSeconds": source_info[0], "referenceStatus": quality["status"],
                          "totalSeconds": round(time.perf_counter() - started, 3),
                          "manifest": str(output / "karaoke_asset_manifest.json")},
                         ensure_ascii=False, indent=2), flush=True)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


if __name__ == "__main__":
    main()
