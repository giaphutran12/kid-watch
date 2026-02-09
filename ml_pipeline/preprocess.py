#!/usr/bin/env python3
"""
Preprocess Kinetics-700 video clips for MoViNet-A2 training.

Scans raw .mp4 clips from data/kinetics700/, maps them to our 3 target
classes (studying, sleeping, other), resizes/resamples frames, and saves
as .npy arrays split into train/val/test sets.

Usage:
    python ml_pipeline/preprocess.py \
        --input-dir data/kinetics700 \
        --output-dir data/processed \
        --fps 5 --frames 50 --size 172
"""

import argparse
import logging
import os
import sys
import time
from multiprocessing import Pool, cpu_count
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from sklearn.model_selection import train_test_split

# Add project root to path so we can import class_mapping
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ml_pipeline.class_mapping import CLASS_MAPPING, CLASS_NAMES, CLASS_TO_INDEX

logging.basicConfig(
    level=logging.INFO,
    format="[PREPROCESS] %(asctime)s %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preprocess Kinetics-700 clips for MoViNet-A2"
    )
    parser.add_argument(
        "--input-dir",
        type=str,
        default="data/kinetics700",
        help="Root dir with class subdirectories of .mp4 files",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data/processed",
        help="Output dir for processed .npy files",
    )
    parser.add_argument(
        "--fps", type=int, default=5, help="Target FPS for resampling (default: 5)"
    )
    parser.add_argument(
        "--frames",
        type=int,
        default=50,
        help="Target frame count per clip (default: 50)",
    )
    parser.add_argument(
        "--size",
        type=int,
        default=172,
        help="Spatial resolution (square, default: 172)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Number of parallel workers (default: cpu_count - 1)",
    )
    parser.add_argument(
        "--train-ratio", type=float, default=0.8, help="Train split ratio"
    )
    parser.add_argument(
        "--val-ratio", type=float, default=0.1, help="Validation split ratio"
    )
    parser.add_argument(
        "--seed", type=int, default=42, help="Random seed for reproducibility"
    )
    return parser.parse_args()


def load_and_process_video(
    video_path: str,
    target_fps: int,
    target_frames: int,
    target_size: int,
) -> Optional[np.ndarray]:
    """
    Load a video, resize frames, resample to target FPS, trim/pad to
    target_frames. Returns float32 array of shape (frames, H, W, 3) in [0,1],
    or None if the video is corrupt/unreadable.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        log.warning("Cannot open video: %s", video_path)
        return None

    src_fps = cap.get(cv2.CAP_PROP_FPS)
    if src_fps <= 0:
        log.warning("Invalid FPS (%.1f) for %s", src_fps, video_path)
        cap.release()
        return None

    # Calculate frame sampling interval
    # e.g. source=30fps, target=5fps → take every 6th frame
    sample_interval = max(1, round(src_fps / target_fps))

    frames = []
    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % sample_interval == 0:
            # Resize to target_size x target_size
            frame_resized = cv2.resize(
                frame, (target_size, target_size), interpolation=cv2.INTER_LINEAR
            )
            # BGR → RGB
            frame_rgb = cv2.cvtColor(frame_resized, cv2.COLOR_BGR2RGB)
            frames.append(frame_rgb)

        frame_idx += 1

    cap.release()

    if len(frames) == 0:
        log.warning("No frames extracted from %s", video_path)
        return None

    # Trim or pad to target_frames
    if len(frames) > target_frames:
        frames = frames[:target_frames]
    elif len(frames) < target_frames:
        # Pad by repeating the last frame
        last_frame = frames[-1]
        while len(frames) < target_frames:
            frames.append(last_frame.copy())

    # Stack into array: (target_frames, H, W, 3)
    clip = np.stack(frames, axis=0)

    # Normalize to [0, 1] float32
    clip = clip.astype(np.float32) / 255.0

    return clip


# Global config for multiprocessing workers (set in main, read by worker)
_worker_config = {}


def _init_worker(target_fps, target_frames, target_size, output_dir):
    """Initializer for pool workers — stores config in global dict."""
    _worker_config["target_fps"] = target_fps
    _worker_config["target_frames"] = target_frames
    _worker_config["target_size"] = target_size
    _worker_config["output_dir"] = output_dir


def _process_one(args: tuple) -> Optional[tuple]:
    """
    Process a single video clip. Called by Pool.map.

    Args:
        args: (video_path, target_class, split, clip_index)

    Returns:
        (target_class, split, output_path) on success, None on failure.
    """
    video_path, target_class, split, clip_index = args

    clip = load_and_process_video(
        video_path,
        _worker_config["target_fps"],
        _worker_config["target_frames"],
        _worker_config["target_size"],
    )

    if clip is None:
        return None

    # Save as .npy
    out_dir = Path(_worker_config["output_dir"]) / split / target_class
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"clip_{clip_index:05d}.npy"
    np.save(str(out_path), clip)

    return (target_class, split, str(out_path))


def collect_clips(input_dir: str) -> list[tuple[str, str]]:
    """
    Scan input_dir for .mp4 files, map to target classes.

    Returns:
        List of (video_path, target_class) tuples.
    """
    clips = []
    input_path = Path(input_dir)

    for subdir in sorted(input_path.iterdir()):
        if not subdir.is_dir():
            continue

        dir_name = subdir.name
        target_class = CLASS_MAPPING.get(dir_name)

        if target_class is None:
            log.warning(
                "Unknown class directory '%s' — skipping (not in CLASS_MAPPING)",
                dir_name,
            )
            continue

        mp4_files = sorted(subdir.glob("*.mp4"))
        for mp4 in mp4_files:
            clips.append((str(mp4), target_class))

        log.info("  %s → %s: %d clips", dir_name, target_class, len(mp4_files))

    return clips


def stratified_split(
    clips: list[tuple[str, str]],
    train_ratio: float,
    val_ratio: float,
    seed: int,
) -> dict[str, list[tuple[str, str]]]:
    """
    Split clips into train/val/test using stratified sampling.

    Returns:
        {"train": [...], "val": [...], "test": [...]}
    """
    paths = [c[0] for c in clips]
    labels = [c[1] for c in clips]

    test_ratio = 1.0 - train_ratio - val_ratio

    # First split: train vs (val+test)
    train_paths, temp_paths, train_labels, temp_labels = train_test_split(
        paths,
        labels,
        test_size=(val_ratio + test_ratio),
        stratify=labels,
        random_state=seed,
    )

    # Second split: val vs test (from the temp set)
    val_fraction = val_ratio / (val_ratio + test_ratio)
    val_paths, test_paths, val_labels, test_labels = train_test_split(
        temp_paths,
        temp_labels,
        test_size=(1 - val_fraction),
        stratify=temp_labels,
        random_state=seed,
    )

    return {
        "train": list(zip(train_paths, train_labels)),
        "val": list(zip(val_paths, val_labels)),
        "test": list(zip(test_paths, test_labels)),
    }


def print_distribution(splits: dict[str, list[tuple[str, str]]]) -> None:
    """Print class distribution per split."""
    print("\n" + "=" * 60)
    print("CLASS DISTRIBUTION REPORT")
    print("=" * 60)

    total_all = 0
    for split_name in ["train", "val", "test"]:
        items = splits[split_name]
        counts = {}
        for _, label in items:
            counts[label] = counts.get(label, 0) + 1

        total = sum(counts.values())
        total_all += total
        print(f"\n  {split_name.upper()} ({total} clips):")
        for cls in CLASS_NAMES:
            n = counts.get(cls, 0)
            pct = (n / total * 100) if total > 0 else 0
            bar = "█" * int(pct / 2)
            print(f"    {cls:12s}: {n:4d}  ({pct:5.1f}%)  {bar}")

    print(f"\n  TOTAL: {total_all} clips")
    print("=" * 60 + "\n")


def main():
    args = parse_args()
    log.info("Starting preprocessing pipeline")
    log.info("  Input:  %s", args.input_dir)
    log.info("  Output: %s", args.output_dir)
    log.info(
        "  Config: %d FPS, %d frames, %dx%d px",
        args.fps,
        args.frames,
        args.size,
        args.size,
    )

    # Step 1: Collect all clips and map to target classes
    log.info("Scanning input directory...")
    clips = collect_clips(args.input_dir)
    log.info("Found %d total clips", len(clips))

    if len(clips) == 0:
        log.error("No clips found — check input directory")
        sys.exit(1)

    # Step 2: Stratified split
    log.info(
        "Splitting data (%.0f%% train / %.0f%% val / %.0f%% test)...",
        args.train_ratio * 100,
        args.val_ratio * 100,
        (1 - args.train_ratio - args.val_ratio) * 100,
    )

    splits = stratified_split(clips, args.train_ratio, args.val_ratio, args.seed)
    print_distribution(splits)

    # Step 3: Process all clips in parallel
    # Build task list: (video_path, target_class, split, global_clip_index)
    tasks = []
    clip_idx = 0
    for split_name in ["train", "val", "test"]:
        for video_path, target_class in splits[split_name]:
            tasks.append((video_path, target_class, split_name, clip_idx))
            clip_idx += 1

    num_workers = args.workers or max(1, cpu_count() - 1)
    log.info("Processing %d clips with %d workers...", len(tasks), num_workers)

    t0 = time.time()

    with Pool(
        processes=num_workers,
        initializer=_init_worker,
        initargs=(args.fps, args.frames, args.size, args.output_dir),
    ) as pool:
        results = pool.map(_process_one, tasks)

    elapsed = time.time() - t0

    # Count successes and failures
    success = sum(1 for r in results if r is not None)
    failed = sum(1 for r in results if r is None)

    log.info("Done in %.1fs — %d succeeded, %d failed", elapsed, success, failed)

    # Step 4: Verify output
    log.info("Verifying output structure...")
    output_path = Path(args.output_dir)
    print("\n" + "=" * 60)
    print("OUTPUT VERIFICATION")
    print("=" * 60)

    for split_name in ["train", "val", "test"]:
        split_dir = output_path / split_name
        print(f"\n  {split_name.upper()}:")
        for cls in CLASS_NAMES:
            cls_dir = split_dir / cls
            if cls_dir.exists():
                npy_files = list(cls_dir.glob("*.npy"))
                # Verify shape of first file
                if npy_files:
                    sample = np.load(str(npy_files[0]))
                    print(
                        f"    {cls:12s}: {len(npy_files):4d} files  shape={sample.shape}  dtype={sample.dtype}"
                    )
                else:
                    print(f"    {cls:12s}:    0 files")
            else:
                print(f"    {cls:12s}: [DIR MISSING]")

    # Disk usage
    total_bytes = sum(f.stat().st_size for f in output_path.rglob("*.npy"))
    print(f"\n  Total disk usage: {total_bytes / (1024**3):.2f} GB")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
