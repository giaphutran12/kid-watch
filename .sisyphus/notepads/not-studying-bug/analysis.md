# KID-WATCH: False "NOT STUDYING" Bug -- Root Cause Analysis
**Date:** 2026-02-11
**Agent:** Atlas (claude-opus-4-6)
**Status:** Analysis complete, ready for implementation

## Working Directory
`/Users/edwardtran/BLI/kid-watch`

## Problem Statement
The system displays "WARNING - NOT STUDYING" on the UI when the kid IS actually studying. Debug CSV logs prove MoViNet correctly predicts "studying" with HIGH confidence (0.77-0.97), yet the displayed state oscillates between STUDYING and NOT STUDYING.

## Evidence from Debug Logs

### `debug_log_20260209_023904.csv`
- Frame 1086: state=WARNING - NOT STUDYING, MoViNet confidence=**0.9178** (92%!), gaze_at_desk=False, pitch=20.8deg
- Frame 1090-1105: NOT STUDYING continues with confidence 0.92-0.93
- Frame 1106: Flips to STUDYING at confidence 0.94
- Pattern repeats: studying/not-studying oscillation despite consistently high MoViNet confidence

### Key Observation
The `source` column is always "studying" (MoViNet says studying), the confidence is always high (0.77-0.97), but the state flips to NOT STUDYING whenever `gaze_at_desk=False`.

## Root Cause: 3-Link Kill Chain

### Link 1: Gaze Gate Hard-Zeros MoViNet (`kid_watch.py:392-394`)
```python
if gaze_at_desk is False:
    studying_confidence = 0.0  # NUKES 92% confidence to ZERO
```

### Link 2: Binary Threshold (`engagement.py:215`)
```python
studying_binary = studying_confidence >= 0.5  # 0.0 < 0.5 -> False
```

### Link 3: Fast Exit Hysteresis (`engagement.py:125`)
```python
STUDYING_EXIT_DWELL = 0.4  # Only 0.4s (~12 frames) to flip state
```

Just 0.4 seconds of `gaze_at_desk=False` -> `studying_confidence=0.0` -> `studying_binary=False` -> state flips to "WARNING - NOT STUDYING".

## Why gaze_at_desk=False When Looking Down?

### Iris Ratio Gate (NOT the cause this time)
`gaze_detector.py:121-126` has an iris_ratio gate, BUT `calibration.py:get_thresholds()` does NOT return `iris_ratio_threshold` -- so iris gate is always disabled. Pitch-only mode is active.

### Actual Cause
- Face detection is **intermittent** (many frames have empty pitch/yaw)
- When face IS detected, pitch hovers around 15deg (threshold boundary)
- Brief dips below 15deg or face detection drops -> `gaze_at_desk=False` or `None`
- When `gaze_at_desk is False` (not None): gaze gate activates

## Architecture Flaw
A **flaky secondary signal** (gaze -- face detection drops, pitch at boundary) is used as a **hard veto** against a **reliable primary signal** (MoViNet -- trained model, EMA smoothing, 92%+ confidence). This is fundamentally wrong.

## Files Involved

| File | Role | Key Lines |
|------|------|-----------|
| `kid_watch.py` | Main pipeline, gaze gate | 386-403 (gaze gate), 704-733 (CSV logging) |
| `kid_watch/engagement.py` | State determination, hysteresis | 109-128 (studying hysteresis), 215 (binary threshold), 224-235 (state mapping) |
| `kid_watch/detectors/gaze_detector.py` | Gaze detection | 91-126 (pitch threshold + iris gate) |
| `kid_watch/detectors/movinet_detector.py` | Action classification | 259-321 (EMA smoothing, confidence) |
| `kid_watch/detectors/state_machine.py` | Internal state enum | 9-17 (State enum), 96-193 (transitions) |
| `kid_watch/calibration.py` | Calibration engine | 590-622 (get_thresholds -- no iris_ratio!) |
| `kid_watch/config.py` | Thresholds | GAZE_DOWN_PITCH_THRESHOLD=15 |
| `kid_watch/dashboard.py` | UI rendering | 357-512 (status panel) |

## Recommended Fixes

### Quick Fix (test immediately)
Remove the gaze gate in `kid_watch.py:392-397` -- delete the 6 lines that zero out studying_confidence based on gaze_at_desk. MoViNet alone drives studying_confidence.

### Proper Fix (production-ready)
1. **Decouple gaze from studying**: `studying_confidence` comes from MoViNet only
2. **Add separate attention signal**: New `attention_confirmed` hysteresis driven by `gaze_at_desk`
3. **New state**: "WARNING - LOOKING AWAY" (studying but not looking at desk)
4. **Reorder state priority**: phone -> not_studying (MoViNet) -> looking_away (gaze) -> slouching -> STUDYING
5. **3-state gaze**: `True` (at desk), `False` (away), `None` (unknown/unreliable) -- treat None as "don't change"

### Key Thresholds Reference
- `STUDYING_CONFIDENCE_THRESHOLD = 0.5` (engagement.py:22)
- `STUDYING_ENTER_DWELL = 0.85s` (engagement.py:31)
- `STUDYING_EXIT_DWELL = 0.4s` (engagement.py:32)
- `GAZE_DOWN_PITCH_THRESHOLD = 15deg` (config.py:14)
- Focus weights: posture=0.30, studying=0.40, no_phone=0.30

## Pipeline Flow Summary
```
Camera -> MoViNet -> action="studying" conf=0.92
       -> GazeDetector -> gaze_at_desk=False (pitch~15deg, intermittent face)
       -> GAZE GATE: conf=0.92 -> 0.0 (ZEROED!)
       -> EngagementEngine: 0.0 < 0.5 -> studying_binary=False
       -> Hysteresis: 0.4s of False -> studying_confirmed=False
       -> State: "WARNING - NOT STUDYING"
```

## Current Phase
Analysis complete. Ready for implementation of fix.

## Next Steps
1. Implement the decoupled gaze/studying architecture
2. Add "WARNING - LOOKING AWAY" state
3. Test with existing debug logs to verify fix
4. Run live test session

## Continue Prompt (for new session)
```
I'm continuing work on the KID-WATCH "false NOT STUDYING" bug fix.
Read the analysis at: .sisyphus/notepads/not-studying-bug/analysis.md
Working directory: /Users/edwardtran/BLI/kid-watch
Current phase: Ready for implementation
Next task: Implement the decoupled gaze/studying architecture (see Recommended Fixes in analysis)
```
