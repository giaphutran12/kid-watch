"""
Scenario parser for kid_watch evaluation.

Defines expected detection states over time ranges in a video.
Supports YAML and JSON formats with flexible time parsing.

Valid states: STUDYING, SLOUCHING, DISTRACTED, WARNING, ABSENT, CALIBRATING, UNKNOWN
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

# Valid expected states
VALID_STATES = {
    "STUDYING",
    "SLOUCHING",
    "DISTRACTED",
    "WARNING",
    "ABSENT",
    "CALIBRATING",
    "NOT_STUDYING",
    "UNKNOWN",
}


def parse_time(value) -> float:
    """
    Parse time value to seconds.

    Supports:
    - "M:SS" format: "2:30" → 150.0
    - "H:MM:SS" format: "1:05:30" → 3930.0
    - Raw seconds: 90 → 90.0, 90.5 → 90.5

    Args:
        value: Time value (str or numeric)

    Returns:
        Time in seconds as float

    Raises:
        ValueError: If format is invalid
    """
    if isinstance(value, (int, float)):
        return float(value)

    if not isinstance(value, str):
        raise ValueError(
            f"[EVAL] Invalid time type: {type(value)}. Expected str or numeric."
        )

    value = value.strip()

    # Try parsing as numeric string
    try:
        return float(value)
    except ValueError:
        pass

    # Parse time format (M:SS or H:MM:SS)
    parts = value.split(":")
    if len(parts) == 2:
        # M:SS format
        try:
            minutes = int(parts[0])
            seconds = float(parts[1])
            return minutes * 60 + seconds
        except ValueError:
            raise ValueError(f"[EVAL] Invalid M:SS format: {value}")
    elif len(parts) == 3:
        # H:MM:SS format
        try:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = float(parts[2])
            return hours * 3600 + minutes * 60 + seconds
        except ValueError:
            raise ValueError(f"[EVAL] Invalid H:MM:SS format: {value}")
    else:
        raise ValueError(
            f"[EVAL] Invalid time format: {value}. Use M:SS, H:MM:SS, or numeric seconds."
        )


@dataclass
class Segment:
    """
    A time segment with expected detection state.

    Attributes:
        start_seconds: Start time in seconds
        end_seconds: End time in seconds
        expected_state: Expected detection state (STUDYING, SLOUCHING, etc.)
        label: Optional description of this segment
    """

    start_seconds: float
    end_seconds: float
    expected_state: str
    label: Optional[str] = None

    def __post_init__(self):
        """Validate segment after initialization."""
        if self.start_seconds < 0:
            raise ValueError(
                f"[EVAL] start_seconds must be >= 0, got {self.start_seconds}"
            )
        if self.end_seconds <= self.start_seconds:
            raise ValueError(
                f"[EVAL] end_seconds ({self.end_seconds}) must be > start_seconds ({self.start_seconds})"
            )
        if self.expected_state not in VALID_STATES:
            print(
                f"[EVAL] WARNING: Unknown state '{self.expected_state}'. "
                f"Valid states: {', '.join(sorted(VALID_STATES))}"
            )

    def contains(self, time_seconds: float) -> bool:
        """Check if time_seconds falls within this segment."""
        return self.start_seconds <= time_seconds < self.end_seconds


@dataclass
class Scenario:
    """
    A complete evaluation scenario with video path and expected states over time.

    Attributes:
        video_path: Path to the video file
        segments: List of time segments with expected states
        metadata: Optional metadata dict (recorded_by, date, description, etc.)
    """

    video_path: str
    segments: List[Segment]
    metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        """Validate scenario after initialization."""
        if not self.video_path:
            raise ValueError("[EVAL] video_path cannot be empty")
        if not self.segments:
            raise ValueError("[EVAL] segments list cannot be empty")

        # Sort segments by start time
        self.segments.sort(key=lambda s: s.start_seconds)

        # Check for overlaps
        for i in range(len(self.segments) - 1):
            if self.segments[i].end_seconds > self.segments[i + 1].start_seconds:
                print(
                    f"[EVAL] WARNING: Segments overlap: "
                    f"[{self.segments[i].start_seconds}, {self.segments[i].end_seconds}) "
                    f"and [{self.segments[i + 1].start_seconds}, {self.segments[i + 1].end_seconds})"
                )

        if not self.metadata:
            self.metadata = {}

    def get_expected_state(self, time_seconds: float) -> Optional[str]:
        """
        Get the expected state for a given timestamp.

        Args:
            time_seconds: Time in seconds

        Returns:
            Expected state string, or None if no segment covers this time
        """
        for segment in self.segments:
            if segment.contains(time_seconds):
                return segment.expected_state
        return None

    def get_segment_at(self, time_seconds: float) -> Optional[Segment]:
        """
        Get the segment containing a given timestamp.

        Args:
            time_seconds: Time in seconds

        Returns:
            Segment object, or None if no segment covers this time
        """
        for segment in self.segments:
            if segment.contains(time_seconds):
                return segment
        return None


def load_scenario(path: str) -> Scenario:
    """
    Load a scenario from a YAML or JSON file.

    YAML format:
        video: data/test-videos/study_session_01.mov
        metadata:
          recorded_by: Edward
          date: 2026-02-09
          description: "10 min study session"
        segments:
          - start: "0:00"
            end: "2:30"
            expected: STUDYING
            label: "Normal studying"
          - start: "2:30"
            end: "3:15"
            expected: SLOUCHING
            label: "Slouch test"

    JSON format:
        {
          "video": "data/test-videos/study_session_01.mov",
          "metadata": {...},
          "segments": [...]
        }

    Args:
        path: Path to YAML or JSON scenario file

    Returns:
        Scenario object

    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If format is invalid
    """
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"[EVAL] Scenario file not found: {path}")

    content = file_path.read_text()

    # Try JSON first (simpler, always available)
    if path.endswith(".json"):
        try:
            data = json.loads(content)
            return _parse_scenario_dict(data)
        except json.JSONDecodeError as e:
            raise ValueError(f"[EVAL] Invalid JSON in {path}: {e}")

    # Try YAML if file ends with .yaml or .yml
    if path.endswith((".yaml", ".yml")):
        try:
            import yaml  # type: ignore[import-not-found]

            data = yaml.safe_load(content)  # type: ignore[attr-defined]
            if not isinstance(data, dict):
                raise ValueError("[EVAL] YAML must contain a dictionary at root level")
            return _parse_scenario_dict(data)
        except ImportError:
            print("[EVAL] WARNING: PyYAML not installed. Trying JSON fallback...")
            try:
                data = json.loads(content)
                return _parse_scenario_dict(data)
            except json.JSONDecodeError as e:
                raise ValueError(
                    f"[EVAL] Could not parse {path} as JSON. "
                    f"Install PyYAML for YAML support: pip install pyyaml"
                ) from e
        except Exception as e:
            raise ValueError(f"[EVAL] Error parsing YAML {path}: {e}")

    # Unknown format
    raise ValueError(f"[EVAL] Unknown file format: {path}. Use .yaml, .yml, or .json")


def _parse_scenario_dict(data: Dict[str, Any]) -> Scenario:
    """
    Parse scenario from dictionary (internal helper).

    Args:
        data: Dictionary with 'video', 'segments', and optional 'metadata'

    Returns:
        Scenario object

    Raises:
        ValueError: If required fields are missing or invalid
    """
    if not isinstance(data, dict):
        raise ValueError("[EVAL] Scenario data must be a dictionary")

    # Extract video path
    video_path = data.get("video")
    if not video_path:
        raise ValueError("[EVAL] 'video' field is required")

    # Extract metadata (optional)
    metadata = data.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("[EVAL] 'metadata' must be a dictionary")

    # Extract and parse segments
    segments_data = data.get("segments")
    if not segments_data:
        raise ValueError("[EVAL] 'segments' field is required and cannot be empty")

    if not isinstance(segments_data, list):
        raise ValueError("[EVAL] 'segments' must be a list")

    segments = []
    for i, seg_data in enumerate(segments_data):
        if not isinstance(seg_data, dict):
            raise ValueError(f"[EVAL] Segment {i} must be a dictionary")

        try:
            start = parse_time(seg_data.get("start"))
            end = parse_time(seg_data.get("end"))
            expected = seg_data.get("expected")
            label = seg_data.get("label")

            if not expected:
                raise ValueError(f"[EVAL] Segment {i}: 'expected' field is required")

            segment = Segment(
                start_seconds=start,
                end_seconds=end,
                expected_state=expected,
                label=label,
            )
            segments.append(segment)
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(f"[EVAL] Error parsing segment {i}: {e}")

    return Scenario(video_path=video_path, segments=segments, metadata=metadata)
