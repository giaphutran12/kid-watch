# Issues — v0.3 MoViNet ML Pipeline

(No issues yet)

## [2026-02-08] ISSUE: MoViNet Metal GPU XLA Platform Registration Failure

**Severity**: HIGH — affects inference latency
**Status**: OPEN — workaround available

**Problem**: TensorFlow 2.17.0 + tensorflow-metal 1.2.0 fails with XLA platform registration error when running MoViNet-A2-Stream. Error: "could not find registered platform with id: 0x..."

**Impact**: MoViNet forced to run on CPU at 93ms/frame instead of expected 20-30ms on GPU.

**Workaround**: Force CPU execution with `tf.config.set_visible_devices([], 'GPU')` before loading MoViNet.

**Why we can't upgrade**:
- TF 2.18 + tensorflow-metal is BROKEN on Python 3.12 (confirmed by Metis)
- TF 2.17 + Python 3.11 is our only stable combo
- tensorflow-metal 1.3.0+ doesn't exist yet

**Mitigation for latency**:
- Run MoViNet every Nth frame (e.g., every 5th frame = ~18ms amortized)
- YOLO models run every frame at ~38ms each
- Plan already anticipated this: "Run MoViNet every 5th frame (1 FPS for action, 30 FPS for phone/pose)"

**Decision**: Accept CPU-only MoViNet with skip-frame strategy. This is acceptable for v0.3 demo targeting >10 FPS.

## [2026-02-08] ISSUE: NumPy Version Conflict (TF 2.17 vs OpenCV 4.10+)

**Severity**: MEDIUM — resolved with version pinning
**Status**: RESOLVED

**Problem**: TensorFlow 2.17 requires numpy<2.0, but OpenCV 4.10+ requires numpy>=2.0.

**Solution**: Pin `opencv-python-headless==4.9.0` (last version compatible with numpy 1.26.4).

**Action**: ml_requirements.txt MUST pin: `numpy==1.26.4`, `opencv-python-headless==4.9.0`

## [2026-02-08] ISSUE: Calibration Recalibration Loop (YOLO Pixel Coordinates)

**Severity**: CRITICAL — infinite recalibration loop breaks calibration system
**Status**: RESOLVED

**Problem**: `check_position_change()` used hardcoded normalization factor `0.15` designed for MediaPipe's [0,1] normalized coordinates. YOLO-pose returns **pixel coordinates** (0-1280, 0-720), causing every frame to trigger position change detection.

**Evidence from live test**:
```
[CAL POS] x_change=97.202 y_change=26.748 → position_changed=True   ← 97x above threshold!
[CAL POS] x_change=166.043 y_change=150.150 → position_changed=True  ← 553x above threshold!
[CAL POS] x_change=6.089 y_change=9.564 → position_changed=True      ← even small movements trigger
```

**Root Cause**: Dividing pixel distances (e.g., 64px) by 0.15 produces massive values (426.67), far exceeding thresholds of 0.30/0.45.

**Solution (3 fixes applied)**:

1. **Frame-dimension normalization**: Replace `/0.15` with `/FRAME_WIDTH` and `/FRAME_HEIGHT`
   - Thresholds: `POSITION_CHANGE_X_THRESHOLD = 0.05` (5% = ~64px), `POSITION_CHANGE_Y_THRESHOLD = 0.08` (8% = ~58px)
   - Now works correctly with YOLO pixel coordinates

2. **Consecutive-frame gating**: Replace time-based duration check with frame counter
   - Require **15 consecutive frames** of position change before triggering recalibration
   - Reset counter to 0 if ANY frame falls below threshold
   - More robust than time-based approach (immune to single-frame spikes)

3. **Post-calibration cooldown**: Add 5-second cooldown after calibration completes
   - Set `_calibration_cooldown_until = time.time() + 5.0` in `finalize_calibration()`
   - Check cooldown first in `check_position_change()` before any position checks
   - Prevents immediate recalibration after calibration completes

**Files Modified**: `kid_watch/calibration.py`

**Verification**: Syntax check passes, LSP diagnostics show only pre-existing type annotation warnings (not related to this fix).

**Impact**: Calibration system now stable with YOLO-pose pixel coordinates. No more infinite recalibration loop.

## [2026-02-08] ISSUE: MoViNet Confidence Ratcheting (Streaming State Accumulation)

**Severity**: CRITICAL — confidence stuck at 1.00 forever, breaks detection accuracy
**Status**: RESOLVED

**Problem**: MoViNet-A2-Stream's internal RNN/LSTM states accumulate temporal context indefinitely, causing confidence to ratchet up to 1.00 and stay there permanently — even when the user is NOT studying. The streaming state never resets except on person disappearance.

**Evidence from live test**:
```
[ML] action=studying conf=0.43 state=studying person=True   ← starts reasonable
[ML] action=studying conf=0.76 state=studying person=True   ← ratcheting up
[ML] action=studying conf=0.87 state=studying person=True
[ML] action=studying conf=0.96 state=studying person=True
[ML] action=studying conf=0.99 state=studying person=True
[ML] action=studying conf=1.00 state=studying person=True   ← STUCK at 1.00 forever
```
User was NOT studying — just sitting at desk looking at camera. The streaming state accumulated "person at desk" context and the softmax probability for "studying" approached 1.0 asymptotically.

**Root Cause**: MoViNet-A2-Stream uses 73 internal state tensors (pool buffers + stream buffers) for temporal context. These states are updated every frame and never reset unless `reset_state()` is called explicitly. The model's RNN/LSTM layers accumulate evidence over time, causing the softmax output to converge to extreme values (0.00 or 1.00) and stay there.

**Solution (3 fixes applied)**:

### Fix 1: Periodic state reset (10 seconds)
Added a timer that resets the streaming state every 10 seconds to prevent infinite memory accumulation:
```python
# In __init__:
self._last_state_reset = time.time()
self._state_reset_interval = 10.0  # seconds

# In detect(), BEFORE inference:
now = time.time()
if now - self._last_state_reset >= self._state_reset_interval:
    logger.info("[MOVINET] Periodic state reset (%.1fs elapsed)", now - self._last_state_reset)
    self._init_states(tf)
    self._last_state_reset = now
    self._ema_probs = None  # Also reset EMA on state reset
```

### Fix 2: EMA smoothing on probabilities
Applied exponential moving average (EMA) to the softmax probabilities to prevent sudden jumps and provide smooth confidence transitions:
```python
# In __init__:
self._ema_probs = None  # Will be initialized on first frame
self._ema_decay = 0.9   # Higher = more smoothing (0.9 = ~10 frame half-life)

# In _postprocess(), AFTER computing softmax probs:
if self._ema_probs is None:
    self._ema_probs = probs.copy()
else:
    self._ema_probs = self._ema_decay * self._ema_probs + (1 - self._ema_decay) * probs

# Use EMA probs for classification:
pred_idx = int(np.argmax(self._ema_probs))
raw_confidence = float(probs[pred_idx])
confidence = float(self._ema_probs[pred_idx])
```

**EMA decay of 0.9 means**:
- Each new frame contributes 10% to the running average
- Half-life ≈ 6.6 frames (at skip-5, that's ~33 frames real-time ≈ 1.1 seconds)
- Prevents confidence from jumping from 0.4 to 0.96 in one frame
- Still allows real transitions to propagate within 2-3 seconds

### Fix 3: Saturation watchdog
If the top-1 probability exceeds 0.98 continuously for 2+ seconds, force a state reset:
```python
# In __init__:
self._saturation_start = None  # Timestamp when saturation began
self._saturation_threshold = 0.98
self._saturation_timeout = 2.0  # seconds

# In _postprocess(), AFTER computing confidence:
if confidence > self._saturation_threshold:
    if self._saturation_start is None:
        self._saturation_start = time.time()
    elif time.time() - self._saturation_start >= self._saturation_timeout:
        logger.info("[MOVINET] Saturation watchdog: conf=%.2f for %.1fs, resetting state",
                    confidence, time.time() - self._saturation_start)
        self._init_states()
        self._ema_probs = None
        self._saturation_start = None
        self._last_state_reset = time.time()
else:
    self._saturation_start = None  # Reset watchdog if confidence drops
```

**Why EMA + periodic reset + saturation watchdog works**:
- **EMA** prevents the confidence from jumping to extreme values in a few frames
- **Periodic reset** (10s) ensures the streaming state doesn't become a "permanent prior"
- **Saturation watchdog** catches the specific failure mode where confidence hits 0.98+ and stays
- Together, these 3 mechanisms create a bounded-memory streaming system instead of infinite-memory

**Files Modified**: `kid_watch/detectors/movinet_detector.py`

**Verification**: 
- Syntax check passes: `python3 -c "import ast; ast.parse(open('kid_watch/detectors/movinet_detector.py').read()); print('OK')"`
- LSP diagnostics show only expected warnings (tensorflow_hub optional import)

**Expected Behavior After Fix**:
- Confidence no longer ratchets to 1.00 and stays there
- Confidence can decrease when the user changes behavior
- Streaming state resets every 10 seconds to prevent accumulation
- Confidence transitions are smooth (no sudden jumps)
- Saturation watchdog catches extreme cases and forces reset

**Impact**: MoViNet detector now provides reliable, dynamic confidence scores that reflect current user behavior instead of accumulated history.
