#!/usr/bin/env python3
"""Kinetics-700 selective downloader for KID-WATCH. Fetches target-class clips via yt-dlp."""

from __future__ import annotations
import argparse, csv, hashlib, json, logging, random, subprocess, sys, threading, time
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

TARGET_CLASSES = ["reading book", "reading newspaper", "writing", "sleeping", "yawning"]
OTHER_SAMPLE_CLASSES = [
    "dancing",
    "cooking",
    "playing guitar",
    "playing piano",
    "singing",
    "riding bicycle",
    "swimming",
    "running",
    "walking the dog",
    "painting",
    "eating",
    "drinking",
    "laughing",
    "crying",
    "stretching",
    "brushing teeth",
    "washing hands",
    "vacuuming",
    "ironing",
    "knitting",
    "juggling",
    "clapping",
    "waving hand",
]
DEFAULT_OUTPUT_DIR = "data/kinetics700"
DEFAULT_MANIFEST_PATH = "data/manifest.json"
DEFAULT_MAX_PER_CLASS = 1000
DEFAULT_OTHER_SAMPLE = 1500
DEFAULT_WORKERS = 4
DEFAULT_MAX_WORKERS = 16
DEFAULT_MIN_WORKERS = 2
DEFAULT_THROTTLE_THRESHOLD_KBPS = 100
MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 2.0
KINETICS_CSV_URL = (
    "https://storage.googleapis.com/deepmind-media/Datasets/kinetics700_2020/train.csv"
)
LABEL_TO_DIR = {
    "reading book": "reading_book",
    "reading newspaper": "reading_newspaper",
    "writing": "writing",
    "sleeping": "sleeping",
    "yawning": "yawning",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("download_kinetics")


@dataclass
class ClipInfo:
    youtube_id: str
    time_start: float
    time_end: float
    split: str
    label: str
    local_path: str | None = None
    sha256: str | None = None
    duration_s: float | None = None


@dataclass
class DownloadStats:
    total: int = 0
    success: int = 0
    skipped: int = 0
    failed: int = 0
    per_class: dict[str, dict[str, int]] = field(default_factory=dict)
    total_bytes: int = 0

    def class_stat(self, cls: str) -> dict[str, int]:
        if cls not in self.per_class:
            self.per_class[cls] = {"total": 0, "success": 0, "skipped": 0, "failed": 0}
        return self.per_class[cls]


class AdaptiveWorkerPool:
    """Adaptive rate-limiting for YouTube downloads. Monitors speed and adjusts worker count."""

    def __init__(
        self,
        max_workers: int,
        min_workers: int,
        throttle_threshold_kbps: float,
    ):
        self.max_workers = max_workers
        self.min_workers = min_workers
        self.throttle_threshold_kbps = throttle_threshold_kbps
        self.current_workers = max_workers
        self.speed_history: deque[float] = deque(maxlen=20)
        self.lock = threading.Lock()
        self.semaphore = threading.Semaphore(max_workers)
        self._adaptive_enabled = max_workers != min_workers

        if self._adaptive_enabled:
            log.info(
                f"[ADAPTIVE] Initialized: max={max_workers}, min={min_workers}, "
                f"threshold={throttle_threshold_kbps:.0f} KB/s"
            )
        else:
            log.info(f"[ADAPTIVE] Disabled (fixed pool: {max_workers} workers)")

    def record_download(self, file_size_bytes: int, duration_seconds: float) -> None:
        """Record a completed download and adjust workers if needed."""
        if not self._adaptive_enabled or duration_seconds <= 0:
            return

        speed_kbps = (file_size_bytes / 1024) / duration_seconds

        with self.lock:
            self.speed_history.append(speed_kbps)

            # Need at least 5 samples before adjusting
            if len(self.speed_history) < 5:
                return

            avg_speed = sum(self.speed_history) / len(self.speed_history)

            # Throttle detected — reduce workers
            if avg_speed < self.throttle_threshold_kbps:
                new_workers = max(self.current_workers // 2, self.min_workers)
                if new_workers < self.current_workers:
                    self._adjust_workers(new_workers, avg_speed, "throttle detected")

            # Speed is healthy — try increasing workers
            elif (
                avg_speed > self.throttle_threshold_kbps * 3
                and self.current_workers < self.max_workers
            ):
                # Binary search up: add half the remaining capacity
                increment = (self.max_workers - self.current_workers) // 2
                new_workers = min(
                    self.current_workers + max(increment, 1), self.max_workers
                )
                if new_workers > self.current_workers:
                    self._adjust_workers(new_workers, avg_speed, "speed healthy")

    def _adjust_workers(self, new_workers: int, avg_speed: float, reason: str) -> None:
        """Adjust worker count and reset speed history."""
        old_workers = self.current_workers
        delta = new_workers - old_workers

        # Adjust semaphore count
        if delta > 0:
            # Increase capacity
            for _ in range(delta):
                self.semaphore.release()
        elif delta < 0:
            # Decrease capacity (acquire without releasing)
            for _ in range(abs(delta)):
                self.semaphore.acquire(blocking=False)

        self.current_workers = new_workers
        self.speed_history.clear()

        log.info(
            f"[ADAPTIVE] {reason.capitalize()}: {avg_speed:.0f} KB/s. "
            f"Workers: {old_workers} → {new_workers}"
        )

    def acquire(self) -> None:
        """Acquire a worker slot (blocks if at capacity)."""
        self.semaphore.acquire()

    def release(self) -> None:
        """Release a worker slot."""
        self.semaphore.release()


def download_csv(url: str, dest: Path) -> Path:
    if dest.exists():
        log.info(f"CSV already exists: {dest}")
        return dest
    log.info(f"Downloading annotation CSV from {url} ...")
    import urllib.request

    dest.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, str(dest))
    log.info(f"Saved CSV to {dest} ({dest.stat().st_size / 1024:.1f} KB)")
    return dest


def parse_csv(csv_path: Path) -> list[ClipInfo]:
    """CSV columns: label, youtube_id, time_start, time_end, split, is_cc (header present)."""
    clips: list[ClipInfo] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            clips.append(
                ClipInfo(
                    youtube_id=row["youtube_id"].strip(),
                    time_start=float(row["time_start"]),
                    time_end=float(row["time_end"]),
                    split=row.get("split", "train").strip(),
                    label=row["label"].strip(),
                )
            )
    log.info(f"Parsed {len(clips)} clips from {csv_path}")
    return clips


def filter_clips(
    clips: list[ClipInfo],
    target_classes: list[str],
    max_per_class: int,
    other_sample: int,
    seed: int = 42,
) -> list[ClipInfo]:
    rng = random.Random(seed)
    by_label: dict[str, list[ClipInfo]] = {}
    for clip in clips:
        by_label.setdefault(clip.label, []).append(clip)
    selected: list[ClipInfo] = []
    for cls in target_classes:
        pool = by_label.get(cls, [])
        rng.shuffle(pool)
        chosen = pool[:max_per_class]
        selected.extend(chosen)
        log.info(f"  {cls}: {len(chosen)} clips (of {len(pool)} available)")
    available_other = [c for c in OTHER_SAMPLE_CLASSES if c in by_label]
    if not available_other:
        available_other = [c for c in by_label if c not in target_classes]
    other_pool: list[ClipInfo] = []
    for cls in available_other:
        other_pool.extend(by_label[cls])
    rng.shuffle(other_pool)
    other_chosen = other_pool[:other_sample]
    for clip in other_chosen:
        clip.label = "other"
    selected.extend(other_chosen)
    log.info(
        f"  other: {len(other_chosen)} clips (from {len(available_other)} classes)"
    )
    return selected


def _output_path(clip: ClipInfo, output_dir: Path) -> Path:
    dir_name = LABEL_TO_DIR.get(clip.label, clip.label.replace(" ", "_"))
    return (
        output_dir
        / dir_name
        / f"{clip.youtube_id}_{int(clip.time_start)}_{int(clip.time_end)}.mp4"
    )


def _ffprobe_duration(path: Path) -> float | None:
    try:
        r = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode == 0 and r.stdout.strip():
            return float(r.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        pass
    return None


def _validate_video(path: Path) -> bool:
    return _ffprobe_duration(path) is not None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _download_single(
    clip: ClipInfo, output_dir: Path, adaptive_pool: AdaptiveWorkerPool | None = None
) -> tuple[ClipInfo, bool, str, int, float]:
    """Download a single clip. Returns (clip, success, message, file_size_bytes, duration_seconds)."""
    out_path = _output_path(clip, output_dir)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists() and out_path.stat().st_size > 0:
        clip.local_path = str(out_path)
        return clip, True, "skipped (exists)", 0, 0.0

    url = f"https://www.youtube.com/watch?v={clip.youtube_id}"
    start, end = int(clip.time_start), int(clip.time_end)
    cmd = [
        "yt-dlp",
        "-f",
        "best[height<=480]/best",
        "--download-sections",
        f"*{start}-{end}",
        "--force-keyframes-at-cuts",
        "--throttled-rate",
        "100K",
        "--sleep-interval",
        "1",
        "--max-sleep-interval",
        "3",
        "--no-warnings",
        "--no-playlist",
        "--quiet",
        "-o",
        str(out_path),
        url,
    ]
    last_err = ""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            download_start = time.time()
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            download_duration = time.time() - download_start

            if (
                result.returncode == 0
                and out_path.exists()
                and out_path.stat().st_size > 0
            ):
                if _validate_video(out_path):
                    clip.local_path = str(out_path)
                    file_size = out_path.stat().st_size
                    if adaptive_pool:
                        adaptive_pool.record_download(file_size, download_duration)
                    return clip, True, "downloaded", file_size, download_duration
                last_err = "ffprobe validation failed"
                out_path.unlink(missing_ok=True)
            else:
                last_err = (
                    result.stderr.strip()[-200:]
                    if result.stderr
                    else f"rc={result.returncode}"
                )
        except subprocess.TimeoutExpired:
            last_err = "timeout (120s)"
        except Exception as e:
            last_err = str(e)[:200]
        if attempt < MAX_RETRIES:
            time.sleep(BACKOFF_BASE_SECONDS**attempt)
    return clip, False, f"failed after {MAX_RETRIES} attempts: {last_err}", 0, 0.0


def download_clips(
    clips: list[ClipInfo],
    output_dir: Path,
    workers: int,
    dry_run: bool = False,
    max_workers: int | None = None,
    min_workers: int | None = None,
    throttle_threshold_kbps: float | None = None,
) -> DownloadStats:
    stats = DownloadStats(total=len(clips))
    if dry_run:
        log.info("[DRY RUN] Skipping actual downloads.")
        for clip in clips:
            cs = stats.class_stat(clip.label)
            cs["total"] += 1
            cs["skipped"] += 1
            stats.skipped += 1
        return stats

    adaptive_pool = None
    if (
        max_workers is not None
        and min_workers is not None
        and throttle_threshold_kbps is not None
    ):
        adaptive_pool = AdaptiveWorkerPool(
            max_workers, min_workers, throttle_threshold_kbps
        )
        effective_workers = max_workers
    else:
        effective_workers = workers

    log.info(f"Starting download: {len(clips)} clips, {effective_workers} workers")

    if adaptive_pool:
        done_count = 0
        with ThreadPoolExecutor(max_workers=effective_workers) as pool:
            futures = {}
            clip_iter = iter(clips)

            for _ in range(min(effective_workers, len(clips))):
                try:
                    clip = next(clip_iter)
                    adaptive_pool.acquire()
                    future = pool.submit(
                        _download_single, clip, output_dir, adaptive_pool
                    )
                    futures[future] = clip
                except StopIteration:
                    break

            while futures:
                done_future = next(as_completed(futures))
                clip = futures.pop(done_future)

                try:
                    clip_result, success, msg, file_size, duration = (
                        done_future.result()
                    )
                finally:
                    adaptive_pool.release()

                done_count += 1
                cs = stats.class_stat(clip_result.label)
                cs["total"] += 1
                if success:
                    if "skipped" in msg:
                        stats.skipped += 1
                        cs["skipped"] += 1
                    else:
                        stats.success += 1
                        cs["success"] += 1
                        if clip_result.local_path:
                            stats.total_bytes += (
                                Path(clip_result.local_path).stat().st_size
                            )
                else:
                    stats.failed += 1
                    cs["failed"] += 1
                    log.debug(f"  FAIL {clip_result.youtube_id}: {msg}")

                try:
                    next_clip = next(clip_iter)
                    adaptive_pool.acquire()
                    future = pool.submit(
                        _download_single, next_clip, output_dir, adaptive_pool
                    )
                    futures[future] = next_clip
                except StopIteration:
                    pass

                if done_count % 50 == 0 or done_count == len(clips):
                    rate = (stats.success + stats.skipped) / max(done_count, 1) * 100
                    log.info(
                        f"  Progress: {done_count}/{len(clips)} "
                        f"(ok={stats.success} skip={stats.skipped} "
                        f"fail={stats.failed} rate={rate:.0f}%)"
                    )
    else:
        with ThreadPoolExecutor(max_workers=effective_workers) as pool:
            futures = {
                pool.submit(_download_single, clip, output_dir, None): clip
                for clip in clips
            }
            done_count = 0
            for future in as_completed(futures):
                clip, success, msg, file_size, duration = future.result()
                done_count += 1
                cs = stats.class_stat(clip.label)
                cs["total"] += 1
                if success:
                    if "skipped" in msg:
                        stats.skipped += 1
                        cs["skipped"] += 1
                    else:
                        stats.success += 1
                        cs["success"] += 1
                        if clip.local_path:
                            stats.total_bytes += Path(clip.local_path).stat().st_size
                else:
                    stats.failed += 1
                    cs["failed"] += 1
                    log.debug(f"  FAIL {clip.youtube_id}: {msg}")
                if done_count % 50 == 0 or done_count == len(clips):
                    rate = (stats.success + stats.skipped) / max(done_count, 1) * 100
                    log.info(
                        f"  Progress: {done_count}/{len(clips)} "
                        f"(ok={stats.success} skip={stats.skipped} "
                        f"fail={stats.failed} rate={rate:.0f}%)"
                    )
    return stats


def generate_manifest(clips: list[ClipInfo], manifest_path: Path) -> int:
    entries = []
    for clip in clips:
        if not clip.local_path or not Path(clip.local_path).exists():
            continue
        path = Path(clip.local_path)
        clip.sha256 = _sha256(path)
        clip.duration_s = _ffprobe_duration(path)
        entries.append(
            {
                "path": clip.local_path,
                "class": clip.label,
                "sha256": clip.sha256,
                "duration_s": clip.duration_s,
                "youtube_id": clip.youtube_id,
            }
        )
    manifest = {
        "version": "1.0",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "total_files": len(entries),
        "files": entries,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    log.info(f"Manifest written: {manifest_path} ({len(entries)} files)")
    return len(entries)


def print_summary(stats: DownloadStats) -> None:
    success_rate = (stats.success + stats.skipped) / max(stats.total, 1) * 100
    size_mb = stats.total_bytes / (1024 * 1024)
    print(f"\n{'=' * 60}\nKINETICS-700 DOWNLOAD SUMMARY\n{'=' * 60}")
    print(
        f"  Total: {stats.total}  Downloaded: {stats.success}  "
        f"Skipped: {stats.skipped}  Failed: {stats.failed}"
    )
    print(f"  Success rate: {success_rate:.1f}%  Total size: {size_mb:.1f} MB")
    print(f"{'-' * 60}")
    for cls, cs in sorted(stats.per_class.items()):
        ok = cs["success"] + cs["skipped"]
        print(f"    {cls:25s}  {ok}/{cs['total']} usable")
    print(f"{'=' * 60}\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Download Kinetics-700 clips for KID-WATCH."
    )
    p.add_argument(
        "--csv-path",
        type=str,
        default=None,
        help="Path to annotation CSV (auto-downloaded if omitted)",
    )
    p.add_argument("--output-dir", type=str, default=DEFAULT_OUTPUT_DIR)
    p.add_argument("--manifest-path", type=str, default=DEFAULT_MANIFEST_PATH)
    p.add_argument(
        "--classes", type=str, default=None, help="Comma-separated target labels"
    )
    p.add_argument("--max-per-class", type=int, default=DEFAULT_MAX_PER_CLASS)
    p.add_argument("--other-sample", type=int, default=DEFAULT_OTHER_SAMPLE)
    p.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    p.add_argument(
        "--max-workers",
        type=int,
        default=DEFAULT_MAX_WORKERS,
        help="Maximum concurrent workers for adaptive rate limiting (default: 16)",
    )
    p.add_argument(
        "--min-workers",
        type=int,
        default=DEFAULT_MIN_WORKERS,
        help="Minimum concurrent workers for adaptive rate limiting (default: 2)",
    )
    p.add_argument(
        "--throttle-threshold",
        type=float,
        default=DEFAULT_THROTTLE_THRESHOLD_KBPS,
        help="Download speed threshold in KB/s for throttle detection (default: 100)",
    )
    p.add_argument("--seed", type=int, default=42)
    p.add_argument(
        "--dry-run", action="store_true", help="Parse CSV only, no downloads"
    )
    p.add_argument("--verbose", "-v", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    output_dir = Path(args.output_dir)
    manifest_path = Path(args.manifest_path)
    target_classes = (
        [c.strip() for c in args.classes.split(",")] if args.classes else TARGET_CLASSES
    )
    if args.csv_path:
        csv_path = Path(args.csv_path)
    else:
        csv_path = Path("data") / "kinetics700_train.csv"
        download_csv(KINETICS_CSV_URL, csv_path)
    if not csv_path.exists():
        log.error(f"CSV not found: {csv_path}")
        return 1
    all_clips = parse_csv(csv_path)
    log.info(f"Found {len(set(c.label for c in all_clips))} unique labels in CSV")
    selected = filter_clips(
        all_clips, target_classes, args.max_per_class, args.other_sample, args.seed
    )
    log.info(f"Selected {len(selected)} clips for download")
    if args.dry_run:
        print("\n[DRY RUN] No downloads will be performed.\n")
        counts = Counter(c.label for c in selected)
        print(f"  CSV file:       {csv_path}")
        print(f"  Total clips:    {len(all_clips)}")
        print(f"  Selected clips: {len(selected)}")
        print(f"  Target classes: {', '.join(target_classes)}\n")
        for cls, count in sorted(counts.items()):
            print(f"    {cls:25s}  {count} clips")
        print()
    stats = download_clips(
        selected,
        output_dir,
        args.workers,
        dry_run=args.dry_run,
        max_workers=args.max_workers,
        min_workers=args.min_workers,
        throttle_threshold_kbps=args.throttle_threshold,
    )
    if not args.dry_run:
        generate_manifest(selected, manifest_path)
    print_summary(stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
