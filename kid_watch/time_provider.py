"""
TimeProvider abstraction for deterministic time handling in video replay mode.

Provides two implementations:
- RealTime: Uses system time (time.time()) for live camera feeds
- VideoTime: Uses frame-based virtual time for deterministic video replay testing

This abstraction enables the same detection pipeline to work in both:
1. Live mode: Real-time camera input with actual system time
2. Video replay mode: Pre-recorded video with deterministic frame-based time
"""

import abc
import time
from typing import Optional


class TimeProvider(abc.ABC):
    """Abstract base class for time providers."""

    @abc.abstractmethod
    def now(self) -> float:
        """Return current time in seconds (float).

        Returns:
            Current time as a float (seconds since epoch for RealTime,
            virtual seconds for VideoTime).
        """
        pass

    @abc.abstractmethod
    def tick(self, cap=None) -> None:
        """Advance time by one frame (no-op for RealTime, increments for VideoTime).

        Args:
            cap: Optional cv2.VideoCapture object. Used by VideoTime to extract
                 actual frame timestamp from video metadata.
        """
        pass


class RealTime(TimeProvider):
    """Real-time provider using system time.

    Used for live camera feeds. Time advances automatically via system clock.
    """

    def now(self) -> float:
        """Return current system time.

        Returns:
            Current time from time.time() (seconds since epoch).
        """
        return time.time()

    def tick(self, cap=None) -> None:
        """No-op for real time (system clock advances automatically)."""
        pass


class VideoTime(TimeProvider):
    """Frame-based virtual time provider for video replay.

    Used for deterministic video replay testing. Time advances per frame
    based on video FPS or explicit frame timestamps from cv2.VideoCapture.

    Attributes:
        fps: Frames per second (used for fallback time increment).
        _current_time: Current virtual time in seconds.
    """

    def __init__(self, fps: float = 30.0) -> None:
        """Initialize VideoTime provider.

        Args:
            fps: Frames per second for fallback time increment (default 30.0).
        """
        self.fps = fps
        self._current_time = 0.0

    def now(self) -> float:
        """Return current virtual time.

        Returns:
            Current virtual time in seconds.
        """
        return self._current_time

    def tick(self, cap=None) -> None:
        """Advance virtual time by one frame.

        Prefers to use cv2.CAP_PROP_POS_MSEC from the VideoCapture object
        if available (actual frame timestamp from video metadata).
        Falls back to 1/fps increment if cap is not provided or timestamp unavailable.

        Args:
            cap: Optional cv2.VideoCapture object. If provided, attempts to extract
                 the current frame's timestamp in milliseconds.
        """
        if cap is not None:
            try:
                import cv2

                pos_msec = cap.get(cv2.CAP_PROP_POS_MSEC)
                if pos_msec > 0:
                    # Convert milliseconds to seconds
                    self._current_time = pos_msec / 1000.0
                    return
            except (ImportError, AttributeError):
                pass

        # Fallback: increment by 1/fps
        delta = 1.0 / self.fps
        self._current_time += delta

    def reset(self) -> None:
        """Reset virtual time to 0."""
        self._current_time = 0.0
