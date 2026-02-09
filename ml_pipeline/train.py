#!/usr/bin/env python3
# pyright: reportMissingImports=false, reportMissingModuleSource=false, reportMissingTypeArgument=false, reportAttributeAccessIssue=false, reportArgumentType=false
"""Train MoViNet-A2-Stream transfer model for KID-WATCH."""

import argparse
import json
import math
import random
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import tensorflow as tf
import tensorflow_hub as hub

# Allow running as a script: `python ml_pipeline/train.py`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ml_pipeline.class_mapping import CLASS_NAMES
from ml_pipeline.data_loader import create_dataset, get_class_weights

TFHUB_URL = (
    "https://tfhub.dev/tensorflow/movinet/a2/stream/kinetics-600/classification/3"
)
INPUT_SIZE = 172


def _log(msg: str) -> None:
    print(f"[TRAIN] {time.strftime('%H:%M:%S')} {msg}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train MoViNet-A2-Stream transfer model (3 classes)"
    )
    parser.add_argument("--data-dir", type=str, default="data/processed")
    parser.add_argument(
        "--model-dir", type=str, default="models/movinet_a2_stream_v0.3"
    )
    parser.add_argument("--results-dir", type=str, default="training_results")
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--epochs-stage1", type=int, default=5)
    parser.add_argument("--epochs-stage2", type=int, default=10)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--stage2-skip-threshold", type=float, default=0.75)
    return parser.parse_args()


def prepare_runtime(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    tf.random.set_seed(seed)
    try:
        tf.config.set_visible_devices([], "GPU")
        _log("Forced CPU mode (Metal XLA workaround)")
    except Exception as exc:  # pragma: no cover
        _log(f"WARNING: could not force CPU mode cleanly: {exc}")


def init_states_for_batch(init_fn, batch_size: tf.Tensor) -> dict[str, tf.Tensor]:
    input_shape = tf.stack([batch_size, 1, INPUT_SIZE, INPUT_SIZE, 3])
    return init_fn(input_shape=tf.cast(input_shape, tf.int32))


def extract_features(
    dataset: tf.data.Dataset,
    split_name: str,
    call_fn,
    init_fn,
) -> tuple[np.ndarray, np.ndarray]:
    start = time.perf_counter()
    feature_chunks: list[np.ndarray] = []
    label_chunks: list[np.ndarray] = []

    for step, (clips, labels) in enumerate(dataset, start=1):
        clips = tf.cast(clips, tf.float32)
        states = init_states_for_batch(init_fn, tf.shape(clips)[0])
        outputs = call_fn(image=clips, **states)

        feature_chunks.append(outputs["logits"].numpy().astype(np.float32))
        label_chunks.append(labels.numpy().astype(np.int32))

        if step % 25 == 0:
            _log(f"[{split_name}] extracted {step} batches")

    if not feature_chunks:
        raise RuntimeError(f"No features extracted for split: {split_name}")

    features = np.concatenate(feature_chunks, axis=0)
    labels = np.concatenate(label_chunks, axis=0)
    minutes = (time.perf_counter() - start) / 60.0
    _log(f"[{split_name}] done: {len(labels)} samples in {minutes:.1f} min")
    return features, labels


def build_head_model(num_classes: int) -> tf.keras.Model:
    return tf.keras.Sequential(
        [
            tf.keras.layers.Input(shape=(600,), name="movinet_logits"),
            tf.keras.layers.Dropout(0.3),
            tf.keras.layers.Dense(num_classes, name="classifier"),
        ],
        name="movinet_transfer_head",
    )


def build_feature_dataset(
    features: np.ndarray,
    labels: np.ndarray,
    batch_size: int,
    shuffle: bool,
    seed: int,
) -> tf.data.Dataset:
    ds = tf.data.Dataset.from_tensor_slices((features, labels))
    if shuffle:
        ds = ds.shuffle(buffer_size=len(labels), seed=seed)
    return ds.batch(batch_size).prefetch(tf.data.AUTOTUNE)


def confusion_and_per_class(
    labels: np.ndarray,
    preds: np.ndarray,
) -> tuple[np.ndarray, list[dict[str, float | int]]]:
    n = len(CLASS_NAMES)
    cm = np.zeros((n, n), dtype=np.int64)
    for true_idx, pred_idx in zip(labels, preds):
        cm[int(true_idx), int(pred_idx)] += 1

    per_class: list[dict[str, float | int]] = []
    for class_idx, class_name in enumerate(CLASS_NAMES):
        tp = float(cm[class_idx, class_idx])
        fp = float(cm[:, class_idx].sum() - tp)
        fn = float(cm[class_idx, :].sum() - tp)
        support = int(cm[class_idx, :].sum())

        precision = tp / (tp + fp + 1e-9)
        recall = tp / (tp + fn + 1e-9)
        f1 = (2.0 * precision * recall) / (precision + recall + 1e-9)

        per_class.append(
            {
                "class": class_name,
                "precision": float(precision),
                "recall": float(recall),
                "f1": float(f1),
                "support": support,
            }
        )
    return cm, per_class


class TransferMoViNet(tf.Module):
    """Wrapper that preserves stream signatures and replaces logits head."""

    def __init__(self, backbone, head):
        super().__init__()
        self.backbone = backbone
        self.head = head

    @tf.function
    def init_states(self, input_shape: tf.Tensor) -> dict[str, tf.Tensor]:
        return self.backbone.signatures["init_states"](input_shape=input_shape)

    @tf.function
    def call(self, image: tf.Tensor, **states: tf.Tensor) -> dict[str, tf.Tensor]:
        outputs = dict(self.backbone.signatures["call"](image=image, **states))
        outputs["logits"] = self.head(outputs["logits"])
        return outputs


def export_model(backbone, head: tf.keras.Model, model_dir: Path) -> None:
    wrapped = TransferMoViNet(backbone=backbone, head=head)

    # Build variables before export.
    states = wrapped.init_states(
        tf.constant([1, 1, INPUT_SIZE, INPUT_SIZE, 3], tf.int32)
    )
    _ = wrapped.call(image=tf.zeros([1, 50, INPUT_SIZE, INPUT_SIZE, 3]), **states)

    call_spec = backbone.signatures["call"].structured_input_signature[1]
    call_signature = wrapped.call.get_concrete_function(**call_spec)
    init_signature = wrapped.init_states.get_concrete_function(
        input_shape=tf.TensorSpec(shape=(5,), dtype=tf.int32, name="input_shape")
    )

    if model_dir.exists():
        shutil.rmtree(model_dir)
    model_dir.parent.mkdir(parents=True, exist_ok=True)

    tf.saved_model.save(
        wrapped,
        str(model_dir),
        signatures={"call": call_signature, "init_states": init_signature},
    )


def main() -> None:
    args = parse_args()
    prepare_runtime(args.seed)

    model_dir = Path(args.model_dir)
    results_dir = Path(args.results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = results_dir / "metrics.json"
    ckpt_path = results_dir / "best_head.weights.h5"

    model_version = (
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}-v0.3-first-train"
    )
    _log(f"model_version={model_version}")

    _log(f"Loading datasets from {args.data_dir}")
    train_clip_ds = create_dataset(
        args.data_dir,
        split="train",
        batch_size=args.batch_size,
        augment=False,
    )
    val_clip_ds = create_dataset(
        args.data_dir,
        split="val",
        batch_size=args.batch_size,
        augment=False,
    )

    class_weights = get_class_weights(args.data_dir, split="train")
    _log(f"class_weights={class_weights}")

    _log(f"Loading TF Hub model: {TFHUB_URL}")
    backbone = hub.load(TFHUB_URL)
    call_fn = backbone.signatures["call"]
    init_fn = backbone.signatures["init_states"]

    train_features, train_labels = extract_features(
        train_clip_ds, "train", call_fn, init_fn
    )
    val_features, val_labels = extract_features(val_clip_ds, "val", call_fn, init_fn)

    head_batch_size = max(32, args.batch_size * 16)
    train_feature_ds = build_feature_dataset(
        train_features,
        train_labels,
        batch_size=head_batch_size,
        shuffle=True,
        seed=args.seed,
    )
    val_feature_ds = build_feature_dataset(
        val_features,
        val_labels,
        batch_size=head_batch_size,
        shuffle=False,
        seed=args.seed,
    )

    head = build_head_model(num_classes=len(CLASS_NAMES))
    callbacks = [
        tf.keras.callbacks.ModelCheckpoint(
            filepath=str(ckpt_path),
            monitor="val_accuracy",
            mode="max",
            save_best_only=True,
            save_weights_only=True,
            verbose=1,
        ),
        tf.keras.callbacks.EarlyStopping(
            monitor="val_accuracy",
            mode="max",
            patience=5,
            restore_best_weights=True,
            verbose=1,
        ),
    ]

    _log(f"Stage1: epochs={args.epochs_stage1}, lr={args.lr:g}")
    head.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=args.lr),
        loss=tf.keras.losses.SparseCategoricalCrossentropy(from_logits=True),
        metrics=["accuracy"],
    )
    history_stage1 = head.fit(
        train_feature_ds,
        validation_data=val_feature_ds,
        epochs=args.epochs_stage1,
        class_weight=class_weights,
        callbacks=callbacks,
        verbose=1,
    )

    stage1_best = float(max(history_stage1.history.get("val_accuracy", [0.0])))
    stage2_skipped = False
    history_stage2: dict[str, list[float]] = {}

    if args.epochs_stage2 > 0:
        if stage1_best >= args.stage2_skip_threshold:
            stage2_skipped = True
            _log(
                "Stage2 skipped: "
                f"stage1 val_accuracy={stage1_best:.4f} >= {args.stage2_skip_threshold:.4f}"
            )
        else:
            stage2_lr = args.lr * 0.1
            steps_per_epoch = max(1, math.ceil(len(train_labels) / head_batch_size))
            lr_schedule = tf.keras.optimizers.schedules.CosineDecay(
                initial_learning_rate=stage2_lr,
                decay_steps=max(1, steps_per_epoch * args.epochs_stage2),
                alpha=0.1,
            )

            _log(
                f"Stage2: epochs={args.epochs_stage2}, "
                f"initial_lr={stage2_lr:g}, cosine_decay"
            )
            head.compile(
                optimizer=tf.keras.optimizers.Adam(learning_rate=lr_schedule),
                loss=tf.keras.losses.SparseCategoricalCrossentropy(from_logits=True),
                metrics=["accuracy"],
            )
            history_stage2 = head.fit(
                train_feature_ds,
                validation_data=val_feature_ds,
                epochs=args.epochs_stage2,
                class_weight=class_weights,
                callbacks=callbacks,
                verbose=1,
            ).history

    if ckpt_path.exists():
        head.load_weights(str(ckpt_path))

    _log(f"Exporting SavedModel to {model_dir}")
    export_model(backbone=backbone, head=head, model_dir=model_dir)

    train_logits = head.predict(train_features, batch_size=256, verbose=0)
    val_logits = head.predict(val_features, batch_size=256, verbose=0)

    train_loss = float(
        tf.reduce_mean(
            tf.keras.losses.sparse_categorical_crossentropy(
                train_labels, train_logits, from_logits=True
            )
        ).numpy()
    )
    val_loss = float(
        tf.reduce_mean(
            tf.keras.losses.sparse_categorical_crossentropy(
                val_labels, val_logits, from_logits=True
            )
        ).numpy()
    )

    train_preds = np.argmax(train_logits, axis=1)
    val_preds = np.argmax(val_logits, axis=1)
    train_accuracy = float(np.mean(train_preds == train_labels))
    val_accuracy = float(np.mean(val_preds == val_labels))
    _, val_per_class = confusion_and_per_class(val_labels, val_preds)

    metrics_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model_version": model_version,
        "model_path": str(model_dir),
        "class_names": CLASS_NAMES,
        "class_weights": {str(k): float(v) for k, v in class_weights.items()},
        "config": {
            "data_dir": args.data_dir,
            "batch_size": args.batch_size,
            "epochs_stage1": args.epochs_stage1,
            "epochs_stage2": args.epochs_stage2,
            "lr": args.lr,
            "head_batch_size": head_batch_size,
            "tfhub_url": TFHUB_URL,
            "cpu_forced": True,
        },
        "history": {
            "stage1": history_stage1.history,
            "stage2": history_stage2,
            "stage2_skipped": stage2_skipped,
        },
        "final_metrics": {
            "train_loss": train_loss,
            "train_accuracy": train_accuracy,
            "val_loss": val_loss,
            "val_accuracy": val_accuracy,
            "val_per_class": val_per_class,
        },
    }

    with metrics_path.open("w", encoding="utf-8") as f:
        json.dump(metrics_payload, f, indent=2)

    _log(f"Saved metrics: {metrics_path}")
    _log(f"Training complete. val_accuracy={val_accuracy:.4f}")


if __name__ == "__main__":
    main()
