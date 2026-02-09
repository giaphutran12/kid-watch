# v0.2 Issues

## [2026-02-08] LSP Warning
- LSP reports `"YOLO" is not exported from module "ultralytics"` — this is a false positive, ultralytics works fine at runtime
- Other LSP errors are from temp files, not our project

## [2026-02-08] Calibration Debug Logging Added

Added comprehensive diagnostic logging to CalibrationEngine to debug stuck-at-100% calibration issue:

**Debug counters added:**
- `_debug_frames_total`: Total frames processed during calibration
- `_debug_frames_pose_ok`: Frames where pose landmarks were detected
- `_debug_add_sample_called`: Times add_sample() was called
- `_debug_samples_accepted`: Samples that passed all validation guards
- Per-guard rejection counters: no_metrics, no_neck_fwd, neck_range, back_range, fwd_lean_range, iris_range, face_small

**Logging behavior:**
- Once-per-second summary during calibration showing all counters and acceptance rate
- On finalize attempt: logs sample count, elapsed time, and samples/second rate
- Counters reset on start_calibration() and trigger_recalibration()

**Expected output format:**
```
[CAL DEBUG] 5.2s | frames=104 pose_ok=98(94%) called=87 accepted=12 | REJECTS: no_metrics=11 no_neck_fwd=0 neck=0 back=0 fwd_lean=0 iris=64 face_small=0
[CAL FINALIZE] samples=12/100 elapsed=20.1s rate=0.6/s
```

This will confirm which hypothesis is correct:
- H1: Face detection missing (high no_metrics)
- H2: Pose missing (low pose_ok%)
- H3: Iris ratio rejecting too many (high iris rejection)

**Next step:** Run the app and analyze debug output to identify root cause.
## [2026-02-08] Side-Angle Camera Bug Fixes

Fixed three bugs discovered during live testing with side-angle camera setup:

### Bug 1: face_width_change triggers false recalibration (line 927)
**Problem:** User did NOT move (x=0, y=0) but face_width fluctuated 38% from side angle, triggering recalibration
**Evidence:** `[POS DEBUG] x_change=0.000 y_change=0.000 face_change=0.387 → position_changed=True`
**Fix:** Removed `face_width_change` from position_changed check entirely — only use X/Y centroid movement
**Rationale:** Face width from side-angle camera is too unreliable for position change detection

### Bug 2: back_angle range [100, 180] rejects ALL samples (line 681)
**Problem:** From side camera, 2D projection of shoulder→hip→knee angle produces values outside [100, 180]
**Evidence:** `REJECTS: back=118 out of 119 frames`
**Fix:** Made back_angle OPTIONAL like iris_ratio — store as None if out of range [80, 180] instead of rejecting sample
**Rationale:** Side-angle cameras make back_angle unreliable, but neck_angle + forward_lean are still valid

### Bug 3: iris_ratio > None TypeError (line 456)
**Problem:** When baseline has `has_iris: False`, `get_thresholds()` returns `iris_ratio_threshold: None`, causing crash
**Evidence:** `TypeError: '>' not supported between instances of 'float' and 'NoneType'`
**Fix:** Added None check before iris comparison — fall back to head pose only if iris_threshold is None
**Rationale:** Side-angle cameras (especially with glasses) don't reliably detect iris, need graceful degradation

**Impact:** All three bugs stem from side-angle camera usage — system now handles this gracefully
**Verification:** `python3 -m py_compile kid_watch.py` passes
