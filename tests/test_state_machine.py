import json
import importlib.util
import unittest
from pathlib import Path

STATE_MACHINE_PATH = Path("kid_watch/detectors/state_machine.py")
STATE_MACHINE_SPEC = importlib.util.spec_from_file_location(
    "state_machine", STATE_MACHINE_PATH
)
state_machine = importlib.util.module_from_spec(STATE_MACHINE_SPEC)
STATE_MACHINE_SPEC.loader.exec_module(state_machine)

DetectionStateMachine = state_machine.DetectionStateMachine
State = state_machine.State


class DetectionStateMachineTests(unittest.TestCase):
    def make_machine(self):
        return DetectionStateMachine(
            fps=1.0,
            studying_enter_frames=1,
            studying_exit_frames=1,
            sleeping_enter_frames=1,
            distracted_seconds=1.0,
            away_seconds=1.0,
            slouch_frames=1,
            session_start_seconds=3.0,
        )

    def test_phone_interruptions_reset_pre_session_studying_progress(self):
        machine = self.make_machine()

        for _ in range(2):
            state, _ = machine.update(action_prediction="studying")
            self.assertEqual(state, State.NOT_STUDYING)

        state, _ = machine.update(action_prediction="studying", phone_detected=True)
        self.assertEqual(state, State.NOT_STUDYING)

        for _ in range(2):
            state, _ = machine.update(action_prediction="studying")
            self.assertEqual(state, State.NOT_STUDYING)

        state, _ = machine.update(action_prediction="studying")
        self.assertEqual(state, State.STUDYING)

    def test_away_frames_reset_pre_session_studying_progress(self):
        machine = self.make_machine()

        for _ in range(2):
            state, _ = machine.update(action_prediction="studying")
            self.assertEqual(state, State.NOT_STUDYING)

        state, _ = machine.update(person_present=False)
        self.assertEqual(state, State.AWAY)

        for _ in range(2):
            state, _ = machine.update(action_prediction="studying")
            self.assertEqual(state, State.NOT_STUDYING)

        state, _ = machine.update(action_prediction="studying")
        self.assertEqual(state, State.STUDYING)


class ScenarioLabelTests(unittest.TestCase):
    def test_one_minute_scenario_matches_pre_session_semantics(self):
        scenario = json.loads(Path("scenarios/footage1_1min.json").read_text())
        expected = {
            segment["expected"]
            for segment in scenario["segments"]
            if "cleaning table" in segment["label"]
        }
        self.assertEqual(expected, {"NOT_STUDYING"})


if __name__ == "__main__":
    unittest.main()
