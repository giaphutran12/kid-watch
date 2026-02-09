#!/usr/bin/env python3
# pyright: reportMissingImports=false, reportMissingModuleSource=false, reportMissingTypeArgument=false, reportArgumentType=false
"""
Evaluate fine-tuned MoViNet-A2-Stream model on test split.

Loads SavedModel from --model-path, runs inference on data/processed/test,
computes confusion matrix + per-class precision/recall/F1, and writes
training_results/confusion_matrix.json.
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import tensorflow as tf

# Allow running as a script: `python ml_pipeline/evaluate.py`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ml_pipeline.class_mapping import CLASS_NAMES
from ml_pipeline.data_loader import create_dataset

logging.basicConfig(
    level=logging.INFO,
    format="[EVAL] %(asctime)s %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

INPUT_SIZE = 172


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate MoViNet-A2-Stream model")
    parser.add_argument(
        "--model-path",
        type=str,
        default="models/movinet_a2_stream_v0.3",
        help="Path to SavedModel directory",
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default="data/processed",
        help="Root data directory containing test split",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=2,
        help="Batch size for evaluation (default: 2)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="training_results",
        help="Directory for confusion matrix output",
    )
    return parser.parse_args()


def force_cpu_mode() -> None:
    try:
        tf.config.set_visible_devices([], "GPU")
        log.info("Forced CPU mode: tf.config.set_visible_devices([], 'GPU')")
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("Could not force CPU mode cleanly: %s", exc)


def _batch_init_states(init_fn, batch_size: tf.Tensor) -> dict[str, tf.Tensor]:
    input_shape = tf.stack(
        [batch_size, tf.constant(1, tf.int32), INPUT_SIZE, INPUT_SIZE, tf.constant(3)]
    )
    return init_fn(input_shape=tf.cast(input_shape, tf.int32))


def compute_confusion_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    class_names: list[str],
) -> tuple[np.ndarray, list[dict[str, float | int]], dict[str, float]]:
    num_classes = len(class_names)
    cm = np.zeros((num_classes, num_classes), dtype=np.int64)
    for true_idx, pred_idx in zip(y_true, y_pred):
        cm[int(true_idx), int(pred_idx)] += 1

    per_class: list[dict[str, float | int]] = []
    precisions: list[float] = []
    recalls: list[float] = []
    f1s: list[float] = []

    for class_idx, class_name in enumerate(class_names):
        tp = float(cm[class_idx, class_idx])
        fp = float(cm[:, class_idx].sum() - tp)
        fn = float(cm[class_idx, :].sum() - tp)
        support = int(cm[class_idx, :].sum())

        precision = tp / (tp + fp + 1e-9)
        recall = tp / (tp + fn + 1e-9)
        f1 = (2.0 * precision * recall) / (precision + recall + 1e-9)

        precisions.append(precision)
        recalls.append(recall)
        f1s.append(f1)

        per_class.append(
            {
                "class": class_name,
                "precision": float(precision),
                "recall": float(recall),
                "f1": float(f1),
                "support": support,
            }
        )

    macro_avg = {
        "precision": float(np.mean(precisions) if precisions else 0.0),
        "recall": float(np.mean(recalls) if recalls else 0.0),
        "f1": float(np.mean(f1s) if f1s else 0.0),
    }

    return cm, per_class, macro_avg


def evaluate_model(
    model,
    dataset: tf.data.Dataset,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    call_fn = model.signatures["call"]
    init_fn = model.signatures["init_states"]

    all_true: list[np.ndarray] = []
    all_pred: list[np.ndarray] = []
    all_probs: list[np.ndarray] = []

    for step, (clips, labels) in enumerate(dataset, start=1):
        clips = tf.cast(clips, tf.float32)
        states = _batch_init_states(init_fn, tf.shape(clips)[0])
        outputs = call_fn(image=clips, **states)
        logits = outputs["logits"]

        probs = tf.nn.softmax(logits, axis=-1).numpy()
        preds = np.argmax(probs, axis=1)

        all_true.append(labels.numpy().astype(np.int32))
        all_pred.append(preds.astype(np.int32))
        all_probs.append(probs.astype(np.float32))

        if step % 20 == 0:
            log.info("Processed %d test batches", step)

    y_true = np.concatenate(all_true, axis=0)
    y_pred = np.concatenate(all_pred, axis=0)
    y_probs = np.concatenate(all_probs, axis=0)
    return y_true, y_pred, y_probs


def maybe_update_metrics_file(
    output_dir: Path,
    test_payload: dict,
) -> None:
    metrics_path = output_dir / "metrics.json"
    if not metrics_path.exists():
        return

    try:
        with metrics_path.open("r", encoding="utf-8") as f:
            metrics_data = json.load(f)
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("Could not read existing metrics.json: %s", exc)
        return

    metrics_data["test_metrics"] = {
        "accuracy": test_payload["test_accuracy"],
        "macro_avg": test_payload["macro_avg"],
        "per_class": test_payload["per_class"],
    }

    with metrics_path.open("w", encoding="utf-8") as f:
        json.dump(metrics_data, f, indent=2)

    log.info("Updated %s with test_metrics", metrics_path)


def main() -> None:
    args = parse_args()
    force_cpu_mode()

    model_path = Path(args.model_path)
    if not model_path.exists():
        raise FileNotFoundError(f"Model path does not exist: {model_path}")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    confusion_path = output_dir / "confusion_matrix.json"

    log.info("Loading model from %s", model_path)
    model = tf.saved_model.load(str(model_path))

    log.info("Loading test dataset from %s", args.data_dir)
    test_ds = create_dataset(
        args.data_dir,
        split="test",
        batch_size=args.batch_size,
        augment=False,
    )

    y_true, y_pred, _ = evaluate_model(model=model, dataset=test_ds)

    accuracy = float(np.mean(y_true == y_pred))
    cm, per_class, macro_avg = compute_confusion_metrics(y_true, y_pred, CLASS_NAMES)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model_path": str(model_path),
        "class_names": CLASS_NAMES,
        "test_samples": int(len(y_true)),
        "test_accuracy": accuracy,
        "macro_avg": macro_avg,
        "per_class": per_class,
        "confusion_matrix": cm.tolist(),
    }

    with confusion_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    maybe_update_metrics_file(output_dir=output_dir, test_payload=payload)

    print("\n" + "=" * 60)
    print("TEST EVALUATION REPORT")
    print("=" * 60)
    print(f"Samples:      {len(y_true)}")
    print(f"Accuracy:     {accuracy:.4f}")
    print(
        "Macro F1:     "
        f"{macro_avg['f1']:.4f} "
        f"(P={macro_avg['precision']:.4f}, R={macro_avg['recall']:.4f})"
    )
    print("\nPer-class metrics:")
    for row in per_class:
        print(
            f"  {row['class']:10s} "
            f"P={row['precision']:.4f} "
            f"R={row['recall']:.4f} "
            f"F1={row['f1']:.4f} "
            f"support={row['support']}"
        )

    print("\nConfusion Matrix (rows=true, cols=pred):")
    print(np.array2string(cm, separator=", "))
    print(f"\nSaved: {confusion_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
