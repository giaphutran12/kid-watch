"""
Frame-by-frame evaluator for KID-WATCH pipeline predictions.

Compares pipeline predictions against ground-truth scenario segments and computes:
- Per-frame accuracy (match/mismatch)
- Per-state precision, recall, F1
- Confusion matrix (expected vs actual)
- Detection delay (reaction time to state transitions)
- Overall accuracy and failure analysis

Methodology:
1. Record each frame with expected_state (from scenario) and actual_state (from pipeline)
2. Skip frames where expected_state is None (unlabeled gaps between segments)
3. Compute confusion matrix: rows=expected, columns=actual
4. For each state transition in the scenario, measure how long until actual_state matches
5. Aggregate stats: TP/FP/FN per state, precision/recall/F1, overall accuracy
"""

from dataclasses import dataclass, field
from typing import cast
from collections import defaultdict


@dataclass
class FrameResult:
    """Result for a single frame evaluation."""

    time_seconds: float
    expected_state: str | None
    actual_state: str
    match: bool
    details: dict[str, object] = field(default_factory=dict)


@dataclass
class EvalStats:
    """Aggregated evaluation statistics."""

    # Per-state counts
    tp: dict[str, int] = field(default_factory=dict)  # True positives per state
    fp: dict[str, int] = field(default_factory=dict)  # False positives per state
    fn: dict[str, int] = field(default_factory=dict)  # False negatives per state

    # Per-state metrics
    precision: dict[str, float] = field(default_factory=dict)
    recall: dict[str, float] = field(default_factory=dict)
    f1: dict[str, float] = field(default_factory=dict)

    # Overall metrics
    overall_accuracy: float = 0.0
    total_frames: int = 0
    labeled_frames: int = 0

    # Confusion matrix: dict[expected_state][actual_state] = count
    confusion_matrix: dict[str, dict[str, int]] = field(default_factory=dict)

    # Transition delays: list of {expected_state, actual_state, delay_seconds}
    transition_delays: list[dict[str, float | str | None]] = field(default_factory=list)


class Evaluator:
    """
    Frame-by-frame evaluator for pipeline predictions.

    Usage:
        evaluator = Evaluator()
        for frame in video:
            expected = scenario.get_expected_state(frame.time)
            evaluator.record(
                time_seconds=frame.time,
                expected_state=expected,
                actual_state=pipeline.predict(frame),
                details={"confidence": 0.95}
            )
        stats = evaluator.compute_stats()
    """

    def __init__(self):
        """Initialize evaluator with empty frame list."""
        self._frames: list[FrameResult] = []
        self._state_transitions: list[dict[str, object]] = []

    def record(
        self,
        time_seconds: float,
        expected_state: str | None,
        actual_state: str,
        details: dict[str, object] | None = None,
    ) -> None:
        """
        Record evaluation result for one frame.

        Args:
            time_seconds: Frame timestamp in seconds
            expected_state: Ground truth state from scenario (None for unlabeled gaps)
            actual_state: Predicted state from pipeline
            details: Optional metadata (confidence, features, etc.)
        """
        if details is None:
            details = {}  # type: ignore

        # Determine if prediction matches expected (skip if expected is None)
        match = (expected_state is not None) and (expected_state == actual_state)

        frame_result = FrameResult(
            time_seconds=time_seconds,
            expected_state=expected_state,
            actual_state=actual_state,
            match=match,
            details=details,
        )
        self._frames.append(frame_result)

        if expected_state is not None:
            if (
                not self._state_transitions
                or self._state_transitions[-1].get("state") != expected_state
            ):
                self._state_transitions.append(
                    {
                        "state": expected_state,  # type: ignore
                        "start_time": time_seconds,  # type: ignore
                        "actual_state_at_transition": actual_state,  # type: ignore
                    }
                )

    def compute_stats(self) -> EvalStats:
        """
        Compute all evaluation metrics from recorded frames.

        Returns:
            EvalStats with TP/FP/FN, precision/recall/F1, confusion matrix, delays
        """
        stats = EvalStats()

        # Filter to labeled frames only
        labeled_frames = [f for f in self._frames if f.expected_state is not None]
        stats.total_frames = len(self._frames)
        stats.labeled_frames = len(labeled_frames)

        if stats.labeled_frames == 0:
            print("[EVAL] No labeled frames to evaluate")
            return stats

        # Initialize confusion matrix and per-state counts
        all_states = set()
        for frame in labeled_frames:
            all_states.add(frame.expected_state)
            all_states.add(frame.actual_state)

        for state in all_states:
            stats.confusion_matrix[state] = defaultdict(int)
            stats.tp[state] = 0
            stats.fp[state] = 0
            stats.fn[state] = 0

        # Build confusion matrix and compute TP/FP/FN
        correct_count = 0
        for frame in labeled_frames:
            expected = frame.expected_state
            actual = frame.actual_state

            # expected_state is never None for labeled frames
            assert expected is not None

            # Update confusion matrix
            stats.confusion_matrix[expected][actual] += 1

            # Update TP/FP/FN
            if expected == actual:
                stats.tp[expected] += 1
                correct_count += 1
            else:
                # This actual_state is a false positive for its state
                stats.fp[actual] += 1
                # This expected_state is a false negative
                stats.fn[expected] += 1

        # Compute overall accuracy
        stats.overall_accuracy = (
            correct_count / stats.labeled_frames if stats.labeled_frames > 0 else 0.0
        )

        # Compute per-state precision, recall, F1
        for state in all_states:
            tp = stats.tp.get(state, 0)
            fp = stats.fp.get(state, 0)
            fn = stats.fn.get(state, 0)

            # Precision = TP / (TP + FP)
            precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            stats.precision[state] = precision

            # Recall = TP / (TP + FN)
            recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            stats.recall[state] = recall

            # F1 = 2 * P * R / (P + R)
            if precision + recall > 0:
                f1 = 2 * precision * recall / (precision + recall)
            else:
                f1 = 0.0
            stats.f1[state] = f1

        # Compute transition delays
        stats.transition_delays = self._compute_transition_delays()

        return stats

    def _compute_transition_delays(self) -> list[dict[str, float | str | None]]:
        """
        Detect state transitions and measure delay until actual_state matches.

        Returns:
            List of {expected_state, actual_state, delay_seconds, transition_time}
        """
        delays: list[dict[str, float | str | None]] = []

        if len(self._state_transitions) < 2:
            return delays

        for i in range(len(self._state_transitions) - 1):
            current_transition = self._state_transitions[i]
            next_transition = self._state_transitions[i + 1]

            expected_from = cast(str, current_transition["state"])
            expected_to = cast(str, next_transition["state"])
            transition_time = cast(float, next_transition["start_time"])

            delay_seconds: float | None = None
            for frame in self._frames:
                if (
                    frame.time_seconds >= transition_time
                    and frame.actual_state == expected_to
                ):
                    delay_seconds = frame.time_seconds - transition_time
                    break

            delays.append(
                {
                    "from_state": expected_from,
                    "to_state": expected_to,
                    "transition_time": transition_time,
                    "delay_seconds": delay_seconds,
                }
            )

        return delays

        # For each transition boundary
        for i in range(len(self._state_transitions) - 1):
            current_transition = self._state_transitions[i]
            next_transition = self._state_transitions[i + 1]

            expected_from = current_transition["state"]
            expected_to = next_transition["state"]
            transition_time = next_transition["start_time"]

            # Find when actual_state first matches expected_to after transition
            delay_seconds = None
            for frame in self._frames:
                if (
                    frame.time_seconds >= transition_time
                    and frame.actual_state == expected_to
                ):
                    delay_seconds = frame.time_seconds - transition_time
                    break

            delays.append(
                {
                    "from_state": expected_from,
                    "to_state": expected_to,
                    "transition_time": transition_time,
                    "delay_seconds": delay_seconds,
                }
            )

        return delays

    def get_failures(self) -> list[FrameResult]:
        """
        Get all frames where expected_state != actual_state.

        Returns:
            List of FrameResult where match=False (excludes unlabeled frames)
        """
        return [f for f in self._frames if f.expected_state is not None and not f.match]

    def get_transition_delays(self) -> list[dict[str, float | str | None]]:
        """
        Get transition delay measurements.

        Returns:
            List of {from_state, to_state, transition_time, delay_seconds}
            delay_seconds is None if actual_state never matched expected_to
        """
        return self._compute_transition_delays()
