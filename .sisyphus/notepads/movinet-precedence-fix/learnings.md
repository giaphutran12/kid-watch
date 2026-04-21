# MoViNet Precedence Fix — Learnings

**Date:** 2026-02-11
**Task:** Fix gaze gate hard-zero bug and rebalance MoViNet precedence

## Changes Made

### 1. Removed Gaze Gate Hard-Zero (kid_watch.py:392-405)

**Before:**
```python
if gaze_at_desk is False:
    studying_confidence = 0.0  # NUKES 92% confidence to ZERO
elif gaze_at_desk is True and studying_confidence == 0.0:
    studying_confidence = 0.5  # Overrides MoViNet
```

**After:**
```python
if gaze_at_desk is False and studying_confidence > 0.0:
    original_confidence = studying_confidence
    studying_confidence = studying_confidence * 0.85  # 15% penalty
elif gaze_at_desk is None:
    pass  # Keep MoViNet confidence as-is
```

**Rationale:**
- Gaze is now a SOFT signal (attention indicator) not a HARD veto
- When looking away: apply 15% penalty (multiply by 0.85) instead of zeroing
- When gaze is unknown (None): don't modify confidence at all
- MoViNet confidence > 0.6 with action="studying" now correctly displays STUDYING

### 2. Increased MoViNet Weight (engagement.py:34-37)

**Before:**
```python
WEIGHT_POSTURE = 0.30
WEIGHT_STUDYING_CONFIDENCE = 0.40  # MoViNet
WEIGHT_NO_PHONE = 0.30
```

**After:**
```python
WEIGHT_POSTURE = 0.20
WEIGHT_STUDYING_CONFIDENCE = 0.55  # MoViNet — primary signal
WEIGHT_NO_PHONE = 0.25
```

**Rationale:**
- MoViNet is the most reliable signal (trained model, EMA smoothing)
- Posture and phone are secondary signals
- Weights still sum to 1.0

### 3. Reduced EMA Asymmetry (movinet_detector.py:56-57)

**Before:**
```python
EMA_DECAY_UP = 0.92  # Slow to rise
EMA_DECAY_DOWN = 0.75  # Fast to fall
```

**After:**
```python
EMA_DECAY_UP = 0.85  # Faster rise
EMA_DECAY_DOWN = 0.82  # Slower fall
```

**Rationale:**
- Previous asymmetry was too biased against "studying"
- Took ~30 frames to reach "studying", dropped in ~10 frames
- New values are more symmetric: faster to rise, slower to fall
- Still maintains some asymmetry (need sustained evidence to enter studying)

## Key Insights

### Architecture Flaw Fixed
A **flaky secondary signal** (gaze — face detection drops, pitch at boundary) was used as a **hard veto** against a **reliable primary signal** (MoViNet — trained model, EMA smoothing, 92%+ confidence). This is fundamentally wrong.

### Gaze as Attention Indicator
Gaze should track **attention** (where the kid is looking), not **activity** (what the kid is doing). MoViNet is the activity classifier.

### Product Decision Preserved
- Slouching while studying = still STUDYING (primary activity wins)
- Brief look-aways (2-3 sec) should still count as STUDYING (soft penalty only)
- Phone detection override in state_machine.py is CORRECT and unchanged

## Testing Notes

### Expected Behavior After Fix
1. When MoViNet says "studying" with confidence > 0.6, system displays STUDYING
2. Brief look-aways apply 15% penalty but don't flip state to NOT STUDYING
3. Gaze=None (face not detected) doesn't modify MoViNet confidence
4. Focus score reflects MoViNet as primary signal (55% weight)

### Debug CSV Verification
Look for `[GAZE-FIX]` log lines in terminal output:
```
[GAZE-FIX] MoViNet conf=0.92 action=studying gaze=False → studying_conf=0.78 (soft penalty)
```

### Backward Compatibility
- No new dependencies
- No API changes
- CSV logging format unchanged (all existing columns intact)
- Session model logic unchanged
- Phone detection override unchanged

## Files Modified
- `kid_watch.py` (lines 392-405): Gaze gate logic
- `kid_watch/engagement.py` (lines 35-37): Weight rebalancing
- `kid_watch/detectors/movinet_detector.py` (lines 56-57): EMA asymmetry

## Next Steps
1. Run live test: `source venv/bin/activate && python kid_watch.py`
2. Verify debug CSV logs show correct behavior
3. Check terminal logs for `[GAZE-FIX]` messages
4. Confirm no false "NOT STUDYING" warnings when kid IS studying
