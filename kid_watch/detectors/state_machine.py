"""KID-WATCH v0.3 — Detection State Machine with debounced transitions."""

import logging
from enum import Enum

logger = logging.getLogger(__name__)


class State(Enum):
    STUDYING = "studying"
    SLEEPING = "sleeping"
    PHONE = "phone"
    SLOUCHING = "slouching"
    DISTRACTED = "distracted"
    AWAY = "away"
    NOT_STUDYING = "not_studying"
    UNKNOWN = "unknown"


class DetectionStateMachine:
    """Fuses MoViNet action + YOLO phone + YOLO pose into a single debounced state."""

    # Magic number constants
    DEBUG_LOG_INTERVAL_FRAMES = 60
    SLOUCHING_CONFIDENCE = 0.8

    def __init__(
        self,
        fps: float = 30.0,
        studying_enter_frames: int = 3,
        studying_exit_frames: int = 5,
        sleeping_enter_frames: int = 3,
        distracted_seconds: float = 2.0,  # Reduced from 8.0 to 2.0 seconds
        away_seconds: float = 3.0,
        slouch_frames: int = 30,
        session_start_seconds: float = 30.0,
    ):
        self.fps = fps
        self.studying_enter_frames = studying_enter_frames
        self.studying_exit_frames = studying_exit_frames
        self.sleeping_enter_frames = sleeping_enter_frames
        self.distracted_frames = int(distracted_seconds * fps)
        self.away_frames = int(away_seconds * fps)
        self.slouch_frames = slouch_frames
        self.session_start_frames = int(session_start_seconds * fps)

        self._state = State.UNKNOWN
        self._confidence = 0.0
        self._frame_count = 0

        self._studying_ct = 0
        self._studying_exit_ct = 0
        self._sleeping_ct = 0
        self._distracted_ct = 0
        self._away_ct = 0
        self._slouch_ct = 0

        self._session_active = False
        self._session_studying_ct = 0

    def update(
        self,
        action_prediction: str = "other",
        action_confidence: float = 0.0,
        phone_detected: bool = False,
        posture_good: bool | None = None,
        person_present: bool = True,
    ) -> tuple[State, float]:
        self._frame_count += 1

        self._evaluate_signals(
            action_prediction,
            action_confidence,
            phone_detected,
            posture_good,
            person_present,
        )

        if self._frame_count % self.DEBUG_LOG_INTERVAL_FRAMES == 0:
            logger.debug(
                "[STATE] frame=%d state=%s conf=%.2f counters: study=%d/%d "
                "sleep=%d distract=%d away=%d slouch=%d",
                self._frame_count,
                self._state.value,
                self._confidence,
                self._studying_ct,
                self._studying_exit_ct,
                self._sleeping_ct,
                self._distracted_ct,
                self._away_ct,
                self._slouch_ct,
            )

        return self._state, self._confidence

    def _evaluate_signals(
        self,
        action_prediction: str,
        action_confidence: float,
        phone_detected: bool,
        posture_good: bool | None,
        person_present: bool,
    ) -> tuple[State, float]:
        if not person_present:
            self._away_ct += 1
            self._reset_non_away_counters()
            if self._away_ct >= self.away_frames:
                self._transition(State.AWAY, 1.0)
            return self._state, self._confidence

        self._away_ct = 0

        if phone_detected:
            self._reset_non_away_counters()
            if self._session_active:
                self._transition(State.PHONE, 1.0)
            else:
                self._transition(State.NOT_STUDYING, 1.0)
            return self._state, self._confidence

        if action_prediction == "sleeping":
            self._sleeping_ct += 1
            self._studying_ct = 0
            self._studying_exit_ct = 0
            self._distracted_ct = 0
            self._slouch_ct = 0
            self._session_studying_ct = 0
            if self._sleeping_ct >= self.sleeping_enter_frames:
                self._transition(State.SLEEPING, action_confidence)
        elif action_prediction == "studying":
            self._sleeping_ct = 0
            self._distracted_ct = 0
            self._studying_ct += 1
            self._studying_exit_ct = 0

            if not self._session_active:
                self._session_studying_ct += 1
                if self._session_studying_ct >= self.session_start_frames:
                    self._session_active = True
                    logger.info(
                        "[SESSION] Session started after %d frames (%.1fs) of sustained studying",
                        self._session_studying_ct,
                        self._session_studying_ct / self.fps,
                    )
                    if self._studying_ct >= self.studying_enter_frames:
                        self._transition(State.STUDYING, action_confidence)

            if self._studying_ct >= self.studying_enter_frames:
                if self._session_active:
                    self._transition(State.STUDYING, action_confidence)
                else:
                    self._transition(State.NOT_STUDYING, action_confidence)
        else:
            self._sleeping_ct = 0
            self._studying_ct = 0
            self._distracted_ct += 1
            self._slouch_ct = 0
            self._session_studying_ct = 0

            if self._state == State.STUDYING:
                self._studying_exit_ct += 1
                if self._studying_exit_ct >= self.studying_exit_frames:
                    self._studying_exit_ct = 0
                    if self._session_active:
                        self._transition(State.DISTRACTED, action_confidence)
                    else:
                        self._transition(State.NOT_STUDYING, action_confidence)
            elif self._distracted_ct >= self.distracted_frames:
                if self._session_active:
                    self._transition(State.DISTRACTED, action_confidence)
                else:
                    self._transition(State.NOT_STUDYING, action_confidence)

        if (
            posture_good is False
            and action_prediction == "studying"
            and self._state
            not in (
                State.AWAY,
                State.PHONE,
                State.SLEEPING,
            )
        ):
            self._slouch_ct += 1
            if self._slouch_ct >= self.slouch_frames:
                if self._session_active:
                    self._transition(State.SLOUCHING, self.SLOUCHING_CONFIDENCE)
                else:
                    self._transition(State.NOT_STUDYING, self.SLOUCHING_CONFIDENCE)
        elif posture_good is True:
            self._slouch_ct = 0

        return self._state, self._confidence

    def _transition(self, new_state: State, confidence: float):
        if new_state != self._state:
            logger.info(
                "[STATE] %s → %s (conf=%.2f, frame=%d)",
                self._state.value,
                new_state.value,
                confidence,
                self._frame_count,
            )
        self._state = new_state
        self._confidence = confidence

    def _reset_non_away_counters(self):
        self._studying_ct = 0
        self._studying_exit_ct = 0
        self._sleeping_ct = 0
        self._distracted_ct = 0
        self._slouch_ct = 0

    def reset(self):
        logger.info("[STATE] Reset")
        self._state = State.UNKNOWN
        self._confidence = 0.0
        self._frame_count = 0
        self._studying_ct = 0
        self._studying_exit_ct = 0
        self._sleeping_ct = 0
        self._distracted_ct = 0
        self._away_ct = 0
        self._slouch_ct = 0
        self._session_active = False
        self._session_studying_ct = 0

    @property
    def state(self) -> State:
        return self._state

    @property
    def confidence(self) -> float:
        return self._confidence
