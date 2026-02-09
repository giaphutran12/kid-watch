"""
Report generator for KID-WATCH evaluation results.

Produces formatted terminal reports from evaluation statistics, failures, and delays.
"""

from typing import List, Optional
from kid_watch.eval.evaluator import EvalStats, FrameResult


def _format_time(seconds: float) -> str:
    """Convert seconds to HH:MM:SS or MM:SS format.

    Args:
        seconds: Time in seconds

    Returns:
        Formatted time string (e.g., "1:30", "1:01:01")
    """
    total_seconds = int(seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60

    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes}:{secs:02d}"


def generate_report(
    stats: EvalStats,
    failures: List[FrameResult],
    delays: List[dict],
    scenario_path: str,
    video_path: str,
) -> str:
    """Generate a formatted evaluation report.

    Args:
        stats: EvalStats dataclass from Evaluator.compute_stats()
        failures: List of FrameResult from Evaluator.get_failures()
        delays: List of delay dicts from Evaluator.get_transition_delays()
        scenario_path: Path to the scenario YAML file
        video_path: Path to the video file

    Returns:
        Formatted report string
    """
    lines = []

    # Header
    lines.append("═" * 63)
    lines.append("  KID-WATCH EVALUATION REPORT")
    lines.append("═" * 63)

    # Metadata
    video_name = video_path.split("/")[-1]
    scenario_name = scenario_path.split("/")[-1]
    total_frames = stats.total_frames
    fps = 30  # Standard assumption
    total_seconds = total_frames / fps

    lines.append(f"  Video:     {video_name}")
    lines.append(f"  Scenario:  {scenario_name}")
    lines.append(
        f"  Frames:    {total_frames} ({total_seconds:.1f} seconds @ {fps}fps)"
    )
    lines.append("─" * 63)

    # Overall accuracy
    accuracy_pct = stats.overall_accuracy * 100
    evaluated = stats.labeled_frames
    unlabeled = stats.total_frames - stats.labeled_frames

    lines.append(f"  OVERALL ACCURACY: {accuracy_pct:.1f}%")
    lines.append(
        f"  Evaluated Frames: {evaluated} / {total_frames} ({unlabeled} unlabeled)"
    )
    lines.append("─" * 63)
    lines.append("")

    # Per-state results table
    lines.append("  PER-STATE RESULTS")
    lines.append("  ┌────────────┬───────────┬────────┬────────┬─────────┐")
    lines.append("  │ State      │ Precision │ Recall │   F1   │ Support │")
    lines.append("  ├────────────┼───────────┼────────┼────────┼─────────┤")

    # Build per-state table from stats attributes
    all_states = (
        set(stats.precision.keys()) | set(stats.recall.keys()) | set(stats.f1.keys())
    )
    for state in sorted(all_states):
        precision = stats.precision.get(state, 0.0)
        recall = stats.recall.get(state, 0.0)
        f1 = stats.f1.get(state, 0.0)
        # Support = TP + FN (all frames where this state was expected)
        support = stats.tp.get(state, 0) + stats.fn.get(state, 0)

        # Pad state name to 10 chars
        state_padded = state.ljust(10)
        lines.append(
            f"  │ {state_padded} │    {precision:.2f}   │  {recall:.2f}  │  {f1:.2f}  │  {support:5d}  │"
        )

    lines.append("  └────────────┴───────────┴────────┴────────┴─────────┘")
    lines.append("")

    # Detection delays
    if delays:
        lines.append("  DETECTION DELAYS")
        lines.append("  ┌──────────────────────────────────────────────────────┐")
        lines.append("  │ Transition              │ Delay  │ At Time           │")
        lines.append("  ├──────────────────────────────────────────────────────┤")

        for delay_info in delays:
            from_state = delay_info.get("from_state", "")
            to_state = delay_info.get("to_state", "")
            transition = f"{from_state} → {to_state}"
            delay_sec = delay_info.get("delay_seconds")
            at_time = delay_info.get("transition_time", 0.0)

            # Pad transition to 23 chars
            transition_padded = transition.ljust(23)
            time_str = _format_time(at_time)

            # Handle None delay (never detected)
            if delay_sec is None:
                delay_str = "  N/A "
            else:
                delay_str = f"{delay_sec:5.1f}s"

            lines.append(f"  │ {transition_padded} │ {delay_str} │ {time_str:17s} │")

        lines.append("  └──────────────────────────────────────────────────────┘")

        # Average delay (only for non-None delays)
        valid_delays: List[float] = [
            d.get("delay_seconds") for d in delays if d.get("delay_seconds") is not None
        ]  # type: ignore
        if valid_delays:
            avg_delay = sum(valid_delays) / len(valid_delays)
            lines.append(f"  Average Detection Delay: {avg_delay:.1f}s")

        lines.append("")

    # Failures - convert FrameResult objects to display format
    if failures:
        lines.append("  FAILURES (showing first 10)")

        # Group consecutive failures
        failure_groups = []
        if failures:
            current_group = [failures[0]]
            for failure in failures[1:]:
                # Group if same expected/actual and within 1 second
                if (
                    failure.expected_state == current_group[-1].expected_state
                    and failure.actual_state == current_group[-1].actual_state
                    and failure.time_seconds - current_group[-1].time_seconds < 1.0
                ):
                    current_group.append(failure)
                else:
                    failure_groups.append(current_group)
                    current_group = [failure]
            failure_groups.append(current_group)

        for i, group in enumerate(failure_groups[:10]):
            start_time = group[0].time_seconds
            end_time = group[-1].time_seconds
            expected = group[0].expected_state
            actual = group[0].actual_state
            duration = end_time - start_time

            start_str = _format_time(start_time)
            end_str = _format_time(end_time)

            lines.append(
                f"  ⚠ {start_str} - {end_str}  Expected {expected}, got {actual} ({duration:.1f}s)"
            )

        if len(failure_groups) > 10:
            remaining = len(failure_groups) - 10
            lines.append(f"  ... and {remaining} more failure groups")
        else:
            lines.append("  ✓ All other segments detected correctly")

        lines.append("")
    else:
        lines.append("  ✓ No failures detected")
        lines.append("")

    # Footer
    lines.append("═" * 63)

    return "\n".join(lines)


def print_report(report_str: str) -> None:
    """Print a report to stdout.

    Args:
        report_str: Report string from generate_report()
    """
    print(report_str)


def save_report(report_str: str, path: str) -> None:
    """Save a report to a file.

    Args:
        report_str: Report string from generate_report()
        path: File path to save to
    """
    with open(path, "w") as f:
        f.write(report_str)
