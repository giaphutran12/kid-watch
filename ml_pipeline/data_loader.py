"""
tf.data pipeline for loading preprocessed .npy clips for MoViNet-A2 training.

Loads preprocessed clips from data/processed/{train,val,test}/{class}/clip_*.npy,
applies optional augmentation (train only), and returns batched tf.data.Datasets.

Usage:
    from ml_pipeline.data_loader import create_dataset

    train_ds = create_dataset("data/processed", split="train", batch_size=4, augment=True)
    val_ds = create_dataset("data/processed", split="val", batch_size=4, augment=False)

    for clips, labels in train_ds:
        # clips: (batch, 50, 172, 172, 3) float32
        # labels: (batch,) int32
        ...
"""

import logging
import os
from pathlib import Path

import numpy as np
import tensorflow as tf

from ml_pipeline.class_mapping import CLASS_NAMES, CLASS_TO_INDEX

logging.basicConfig(
    level=logging.INFO,
    format="[DATA_LOADER] %(asctime)s %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def _collect_npy_paths(data_dir: str, split: str) -> tuple[list[str], list[int]]:
    """
    Collect all .npy file paths and their integer labels for a given split.

    Returns:
        (paths, labels) where paths is a list of file path strings and
        labels is a list of integer class indices.
    """
    split_dir = Path(data_dir) / split
    paths = []
    labels = []

    for class_name in CLASS_NAMES:
        class_dir = split_dir / class_name
        if not class_dir.exists():
            log.warning("Class dir missing: %s", class_dir)
            continue

        class_idx = CLASS_TO_INDEX[class_name]
        npy_files = sorted(class_dir.glob("*.npy"))

        for npy_file in npy_files:
            paths.append(str(npy_file))
            labels.append(class_idx)

    log.info(
        "Collected %d clips for split='%s' from %s",
        len(paths),
        split,
        split_dir,
    )
    return paths, labels


def _load_npy(path: tf.Tensor) -> tf.Tensor:
    """Load a .npy file and return as float32 tensor."""

    def _np_load(path_bytes):
        path_str = path_bytes.numpy().decode("utf-8")
        clip = np.load(path_str)
        return clip.astype(np.float32)

    clip = tf.py_function(_np_load, [path], tf.float32)
    return clip


def _augment_clip(clip: tf.Tensor) -> tf.Tensor:
    """
    Apply basic spatial augmentation to a video clip.

    Augmentations (applied identically to all frames in a clip):
    - Random horizontal flip (50% chance)
    - Random brightness adjustment (±0.1)
    - Random contrast adjustment (±0.1)

    Args:
        clip: Tensor of shape (frames, H, W, 3), float32 in [0, 1]

    Returns:
        Augmented clip, same shape, clamped to [0, 1]
    """
    # Random horizontal flip — flip all frames consistently
    if tf.random.uniform([]) > 0.5:
        clip = tf.reverse(clip, axis=[2])  # flip width axis

    # Random brightness — same delta for all frames
    delta = tf.random.uniform([], minval=-0.1, maxval=0.1)
    clip = clip + delta

    # Random contrast — same factor for all frames
    factor = tf.random.uniform([], minval=0.9, maxval=1.1)
    clip = (clip - 0.5) * factor + 0.5

    # Clamp to [0, 1]
    clip = tf.clip_by_value(clip, 0.0, 1.0)

    return clip


def create_dataset(
    data_dir: str,
    split: str = "train",
    batch_size: int = 4,
    augment: bool = True,
    shuffle_buffer: int = 256,
    seed: int = 42,
) -> tf.data.Dataset:
    """
    Create a tf.data.Dataset for MoViNet-A2 training/evaluation.

    Args:
        data_dir: Root directory containing {train,val,test}/{class}/*.npy
        split: One of "train", "val", "test"
        batch_size: Batch size
        augment: Whether to apply data augmentation (typically True for train only)
        shuffle_buffer: Size of the shuffle buffer
        seed: Random seed for shuffling

    Returns:
        tf.data.Dataset yielding (clips, labels) where:
            clips: float32 tensor of shape (batch, frames, H, W, 3)
            labels: int32 tensor of shape (batch,)
    """
    paths, labels = _collect_npy_paths(data_dir, split)

    if len(paths) == 0:
        raise ValueError(
            f"No .npy files found for split='{split}' in {data_dir}. "
            "Run preprocess.py first."
        )

    # Create dataset from file paths and labels
    path_ds = tf.data.Dataset.from_tensor_slices(paths)
    label_ds = tf.data.Dataset.from_tensor_slices(tf.cast(labels, tf.int32))

    # Load .npy files
    clip_ds = path_ds.map(_load_npy, num_parallel_calls=tf.data.AUTOTUNE)

    # Zip clips with labels
    ds = tf.data.Dataset.zip((clip_ds, label_ds))

    # Shuffle (train only, or when augment is True)
    if split == "train":
        ds = ds.shuffle(buffer_size=shuffle_buffer, seed=seed)

    # Apply augmentation to clips only
    if augment and split == "train":

        def _augment_fn(clip, label):
            return _augment_clip(clip), label

        ds = ds.map(_augment_fn, num_parallel_calls=tf.data.AUTOTUNE)

    # Set static shape (tf.py_function loses shape info)
    def _set_shape(clip, label):
        clip.set_shape([None, None, None, 3])  # (frames, H, W, 3)
        return clip, label

    ds = ds.map(_set_shape)

    # Batch and prefetch
    ds = ds.batch(batch_size)
    ds = ds.prefetch(tf.data.AUTOTUNE)

    log.info(
        "Created dataset: split=%s, %d clips, batch_size=%d, augment=%s",
        split,
        len(paths),
        batch_size,
        augment,
    )

    return ds


def get_class_weights(data_dir: str, split: str = "train") -> dict[int, float]:
    """
    Compute class weights inversely proportional to frequency for imbalanced data.

    Returns:
        Dict mapping class_index → weight (higher weight for rarer classes).
    """
    _, labels = _collect_npy_paths(data_dir, split)

    if len(labels) == 0:
        return {}

    counts = {}
    for label in labels:
        counts[label] = counts.get(label, 0) + 1

    total = sum(counts.values())
    n_classes = len(CLASS_NAMES)

    weights = {}
    for cls_idx in range(n_classes):
        count = counts.get(cls_idx, 1)
        # Balanced weight: total / (n_classes * count)
        weights[cls_idx] = total / (n_classes * count)

    log.info("Class weights: %s", weights)
    return weights


if __name__ == "__main__":
    import sys

    data_dir = sys.argv[1] if len(sys.argv) > 1 else "data/processed"

    print(f"\nLoading datasets from: {data_dir}\n")

    for split in ["train", "val", "test"]:
        try:
            ds = create_dataset(
                data_dir,
                split=split,
                batch_size=4,
                augment=(split == "train"),
            )

            # Peek at one batch
            for clips, labels in ds.take(1):
                print(
                    f"  {split:5s}: clips={clips.shape}, "
                    f"labels={labels.shape}, "
                    f"dtype={clips.dtype}, "
                    f"range=[{tf.reduce_min(clips):.3f}, {tf.reduce_max(clips):.3f}]"
                )
                break
        except ValueError as e:
            print(f"  {split:5s}: {e}")

    # Print class weights
    print()
    weights = get_class_weights(data_dir, "train")
    for cls_name in CLASS_NAMES:
        idx = CLASS_TO_INDEX[cls_name]
        w = weights.get(idx, 0)
        print(f"  {cls_name}: weight={w:.3f}")
