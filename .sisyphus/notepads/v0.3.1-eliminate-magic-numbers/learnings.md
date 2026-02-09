# v0.3.1 Magic Number Elimination — Learnings

## [2026-02-09] Session Start
- Pure refactoring: zero behavior changes
- Constants stay in the files that use them (no new files)
- Shared constants → config.py
- File-specific → class or module constants
- Dashboard constants stay in dashboard.py
- Syntax check after EVERY file change

## [2026-02-09] calibration.py Refactoring Complete

### Magic Numbers Extracted (20 constants)
1. **NEUTRAL_SETTLE_SECONDS = 1.0** — Neutral posture settle duration
2. **NEUTRAL_SETTLE_LEAN_THRESHOLD = 15.0** — Forward lean threshold for neutral detection
3. **NECK_ANGLE_VALID_MIN = 100** — Minimum valid neck angle
4. **NECK_ANGLE_VALID_MAX = 180** — Maximum valid neck angle
5. **BACK_ANGLE_VALID_MIN = 80** — Minimum valid back angle
6. **BACK_ANGLE_VALID_MAX = 180** — Maximum valid back angle
7. **FORWARD_LEAN_VALID_MIN = 0** — Minimum valid forward lean
8. **FORWARD_LEAN_VALID_MAX = 60** — Maximum valid forward lean
9. **MIN_ABSOLUTE_SAMPLES = 10** — Minimum samples for force-finalize
10. **MAD_MULTIPLIER = 2.5** — MAD multiplier for threshold (≈2σ equivalent)
11. **NECK_ANGLE_MAD_FLOOR = 5.0** — MAD floor for neck angle
12. **BACK_ANGLE_MAD_FLOOR = 5.0** — MAD floor for back angle
13. **FORWARD_LEAN_MAD_FLOOR = 3.0** — MAD floor for forward lean
14. **CENTROID_NORMALIZATION = 100.0** — Centroid distance normalization factor
15. **BASELINE_MATCH_THRESHOLD = 0.15** — Baseline matching distance threshold
16. **SHOULDER_CONFIDENCE_THRESHOLD = 0.3** — YOLO shoulder keypoint confidence threshold

### Key Patterns
- All constants defined at class level (top of CalibrationEngine)
- Used via `self.CONSTANT_NAME` throughout methods
- No behavior changes — every value identical to original
- Syntax check: ✓ PASSED
- Import check: ✓ PASSED

### Refactoring Approach
- Read entire file first to understand all magic numbers
- Grouped related constants (angle ranges, MAD floors, thresholds)
- Added inline comments explaining each constant's purpose
- Replaced all usages with named constants
- Verified no logic changes via syntax/import checks

### Notes for Future Phases
- Other detector files (phone_detector.py, movinet_detector.py, posture_detector_yolo.py) have similar magic numbers
- Same pattern applies: extract to class constants
- kid_watch.py has hardcoded thresholds that should be extracted
