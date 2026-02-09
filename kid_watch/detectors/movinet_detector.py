"""
KID-WATCH v0.3 — MoViNet-A2-Stream Detector

Forces CPU mode to work around Metal GPU XLA bug (TF 2.17 + tensorflow-metal 1.2.0).
"""

import logging
import os
import time
from typing import TYPE_CHECKING

import numpy as np

from kid_watch.time_provider import RealTime

if TYPE_CHECKING:
    import tensorflow as tf

logger = logging.getLogger(__name__)

TFHUB_MOVINET_A2_URL = (
    "https://tfhub.dev/tensorflow/movinet/a2/stream/kinetics-600/classification/3"
)
DEFAULT_MODEL_PATH = "models/movinet_a2_stream_v0.3"
INPUT_HEIGHT = 172
INPUT_WIDTH = 172
CLASS_NAMES_FINETUNED = {0: "studying", 1: "other", 2: "other"}
CONFIDENCE_THRESHOLD = 0.4


def _force_cpu():
    """Metal GPU XLA bug workaround — must be called before any model load."""
    import tensorflow as tf

    try:
        gpus = tf.config.list_physical_devices("GPU")
        if gpus:
            tf.config.set_visible_devices([], "GPU")
            logger.info("[MOVINET] Forced CPU mode (Metal XLA workaround)")
    except RuntimeError:
        logger.warning("[MOVINET] Could not set CPU mode — devices already initialized")


class MoViNetDetector:
    """
    MoViNet-A2-Stream wrapper for per-frame streaming action recognition.

    Fine-tuned mode: 3-class SavedModel (studying/sleeping/other).
    Pre-trained mode: TF Hub 600-class Kinetics-600 (testing only).
    """

    # Magic number constants
    SAFETY_RESET_INTERVAL = 30.0  # Level 2: Safety reset every 30s (keeps EMA)
    # Asymmetric EMA: confidence drops faster than it rises
    # This prevents the system from staying "stuck" on studying for ~30 seconds
    # when the student stops studying. Slow promote ensures brief glances at desk
    # don't immediately register as studying.
    EMA_DECAY_UP = 0.92  # Slow to promote: need sustained studying evidence
    EMA_DECAY_DOWN = 0.75  # Fast to demote: quickly drops when MoViNet says "other"
    DISAGREEMENT_THRESHOLD = 2.0  # seconds of disagreement before reset
    LOG_INTERVAL_FRAMES = 30  # Log inference timing every N frames
    NUM_CLASSES_TFHUB = 600  # Kinetics-600 pre-trained model
    NUM_CLASSES_FINETUNED = 3  # Fine-tuned model (studying/other/other)

    def __init__(
        self,
        model_path: str | None = DEFAULT_MODEL_PATH,
        use_tfhub: bool = False,
        confidence_threshold: float = CONFIDENCE_THRESHOLD,
        time_provider=None,
    ):
        self.model_path = model_path
        self.use_tfhub = use_tfhub
        self.confidence_threshold = confidence_threshold
        self._time_provider = time_provider or RealTime()

        self._model = None
        self._states = None
        self._is_finetuned = False
        self._num_classes = 0
        self._loaded = False
        self._frame_count = 0

        # 3-Level Reset System
        self._last_state_reset = self._time_provider.now()

        # EMA smoothing on probabilities
        self._ema_probs = None  # Will be initialized on first frame

        # Level 1: Conditional reset (raw disagrees with EMA)
        self._disagreement_start = None  # When raw started disagreeing with EMA

        # Load model synchronously
        self._load_model()

    def _load_model(self):
        try:
            _force_cpu()
            import tensorflow as tf

            if self.use_tfhub:
                self._load_from_tfhub(tf)
            else:
                self._load_from_saved_model(tf)

        except ImportError:
            logger.error(
                "[MOVINET] TensorFlow not installed — "
                "MoViNet detector disabled. Install with: pip install tensorflow"
            )
            return
        except Exception as e:
            logger.error("[MOVINET] Failed to load model: %s", e)
            return

    def _load_from_tfhub(self, tf):
        try:
            import tensorflow_hub as hub
        except ImportError:
            logger.error(
                "[MOVINET] tensorflow_hub not installed — "
                "cannot load from TF Hub. Install with: pip install tensorflow-hub"
            )
            return

        logger.info("[MOVINET] Loading pre-trained model from TF Hub...")
        t0 = time.perf_counter()
        self._model = hub.load(TFHUB_MOVINET_A2_URL)
        dt = time.perf_counter() - t0
        logger.info("[MOVINET] Pre-trained model loaded in %.1fs", dt)

        self._is_finetuned = False
        self._num_classes = self.NUM_CLASSES_TFHUB
        self._loaded = True
        self._init_states(tf)

    def _load_from_saved_model(self, tf):
        if not self.model_path or not os.path.isdir(self.model_path):
            logger.warning(
                "[MOVINET] Model not found at '%s' — "
                "detector disabled. Train model first (Phase 4).",
                self.model_path,
            )
            return

        logger.info("[MOVINET] Loading fine-tuned model from %s...", self.model_path)
        t0 = time.perf_counter()
        self._model = tf.saved_model.load(self.model_path)
        dt = time.perf_counter() - t0
        logger.info("[MOVINET] Fine-tuned model loaded in %.1fs", dt)

        self._is_finetuned = True
        self._num_classes = self.NUM_CLASSES_FINETUNED
        self._loaded = True
        self._init_states(tf)

    def _init_states(self, tf=None):
        """Reset streaming states ONLY. Does NOT reset EMA (EMA bridges across resets)."""
        if self._model is None:
            return

        if tf is None:
            import tensorflow as tf

        try:
            input_shape = tf.constant(
                [1, 1, INPUT_HEIGHT, INPUT_WIDTH, 3], dtype=tf.int32
            )
            init_states_fn = self._model.signatures["init_states"]
            self._states = init_states_fn(input_shape=input_shape)
            logger.info(
                "[MOVINET] Streaming state initialized (%d tensors)",
                len(self._states),
            )
            # DO NOT reset self._ema_probs here — EMA bridges across streaming state resets
        except (KeyError, TypeError) as e:
            logger.error("[MOVINET] Failed to initialize streaming states: %s", e)
            self._model = None
            self._loaded = False

    def detect(self, frame_rgb: np.ndarray) -> tuple[str, float, np.ndarray | None]:
        """
        Run streaming inference on a single full frame.

        Returns (class_name, confidence, raw_logits). Falls back to ("other", 0.0, None).
        """
        if not self._loaded or self._model is None:
            return "other", 0.0, None

        try:
            import tensorflow as tf
        except ImportError:
            return "other", 0.0, None

        self._frame_count += 1
        t0 = time.perf_counter()

        try:
            # Level 2: Safety reset (every 30 seconds, keep EMA)
            now = self._time_provider.now()
            if now - self._last_state_reset >= self.SAFETY_RESET_INTERVAL:
                logger.info(
                    "[MOVINET] Safety reset (%.1fs elapsed)",
                    now - self._last_state_reset,
                )
                self._init_states(tf)
                self._last_state_reset = now
                # DO NOT reset self._ema_probs — EMA bridges across the reset!

            frame_tensor = self._preprocess_frame(frame_rgb, tf)

            call_fn = self._model.signatures["call"]
            outputs = call_fn(image=frame_tensor, **self._states)

            logits = None
            new_states = {}
            for key, val in outputs.items():
                if key == "logits":
                    logits = val
                else:
                    new_states[key] = val

            self._states = new_states

            if logits is None:
                logger.warning("[MOVINET] No logits in model output")
                return "other", 0.0, None

            logits_np = logits.numpy()

            dt_ms = (time.perf_counter() - t0) * 1000
            if self._frame_count % self.LOG_INTERVAL_FRAMES == 0:
                logger.debug(
                    "[MOVINET] Inference: %.1fms (frame %d)", dt_ms, self._frame_count
                )

            return self._postprocess(logits_np)

        except Exception as e:
            logger.error(
                "[MOVINET] Inference error on frame %d: %s", self._frame_count, e
            )
            return "other", 0.0, None

    def _preprocess_frame(self, frame_rgb: np.ndarray, tf: "tf") -> "tf.Tensor":
        if frame_rgb.dtype == np.uint8:
            frame = frame_rgb.astype(np.float32) / 255.0
        else:
            frame = frame_rgb.astype(np.float32)
            if frame.max() > 1.0:
                frame = frame / 255.0

        frame_tensor = tf.image.resize(frame, [INPUT_HEIGHT, INPUT_WIDTH])
        # (H,W,3) → (1,1,H,W,3): batch + time dims for MoViNet streaming input
        frame_tensor = tf.expand_dims(tf.expand_dims(frame_tensor, 0), 1)

        return frame_tensor

    def _postprocess(self, logits_np: np.ndarray) -> tuple[str, float, np.ndarray]:
        logits_flat = logits_np.squeeze()
        probs = _softmax(logits_flat)

        # EMA smoothing on probabilities (asymmetric: drops faster than rises)
        if self._ema_probs is None:
            self._ema_probs = probs.copy()
        else:
            # Asymmetric EMA: per-class decay based on whether probability is rising or falling
            for i in range(len(probs)):
                if probs[i] >= self._ema_probs[i]:
                    decay = (
                        self.EMA_DECAY_UP
                    )  # rising: smooth slowly (need sustained evidence)
                else:
                    decay = self.EMA_DECAY_DOWN  # falling: react quickly (drop fast)
                self._ema_probs[i] = decay * self._ema_probs[i] + (1 - decay) * probs[i]

        # Raw vs EMA predictions
        raw_pred_idx = int(np.argmax(probs))  # Raw prediction
        ema_pred_idx = int(np.argmax(self._ema_probs))  # EMA prediction
        raw_confidence = float(probs[raw_pred_idx])
        confidence = float(self._ema_probs[ema_pred_idx])

        # Level 1: Conditional reset (raw disagrees with EMA for 2 seconds)
        if raw_pred_idx != ema_pred_idx:
            # Raw disagrees with EMA
            if self._disagreement_start is None:
                self._disagreement_start = self._time_provider.now()
            elif (
                self._time_provider.now() - self._disagreement_start
                >= self.DISAGREEMENT_THRESHOLD
            ):
                logger.info(
                    "[MOVINET] Conditional reset: raw=%s disagrees with EMA=%s for %.1fs",
                    CLASS_NAMES_FINETUNED.get(raw_pred_idx, "?"),
                    CLASS_NAMES_FINETUNED.get(ema_pred_idx, "?"),
                    self._time_provider.now() - self._disagreement_start,
                )
                self._init_states()  # Reset streaming state
                # DO NOT reset self._ema_probs — EMA bridges across the reset!
                self._disagreement_start = None
                self._last_state_reset = self._time_provider.now()
        else:
            self._disagreement_start = None  # Agreement → reset counter

        logger.debug(
            "[MOVINET] raw=%s(%.2f) ema=%s(%.2f) disagreeing=%s",
            CLASS_NAMES_FINETUNED.get(raw_pred_idx, "?"),
            raw_confidence,
            CLASS_NAMES_FINETUNED.get(ema_pred_idx, "?"),
            confidence,
            "YES" if self._disagreement_start else "no",
        )

        if not self._is_finetuned:
            return f"kinetics_{ema_pred_idx}", confidence, logits_flat

        if confidence < self.confidence_threshold:
            return "other", confidence, logits_flat

        class_name = CLASS_NAMES_FINETUNED.get(ema_pred_idx, "other")
        return class_name, confidence, logits_flat

    def reset_state(self):
        """Level 3: Hard reset — person disappeared. Wipe everything including EMA."""
        if not self._loaded or self._model is None:
            return

        logger.info("[MOVINET] Hard reset (person disappeared)")
        self._init_states()
        self._frame_count = 0
        self._last_state_reset = self._time_provider.now()
        self._ema_probs = None  # ONLY Level 3 resets EMA
        self._disagreement_start = None

    @property
    def is_loaded(self) -> bool:
        return self._loaded and self._model is not None

    @property
    def is_finetuned(self) -> bool:
        return self._is_finetuned


def _softmax(logits: np.ndarray) -> np.ndarray:
    SOFTMAX_EPSILON = 1e-9
    exp_logits = np.exp(logits - np.max(logits))
    return exp_logits / (exp_logits.sum() + SOFTMAX_EPSILON)
