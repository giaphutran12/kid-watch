# Tuning Loop Decisions

## [2026-02-10] Strategy
- Run baseline first, then analyze failure patterns before changing anything
- Commit each iteration for rollback
- Use Gemini 3 Flash Preview for ambiguous frames
- Target: 98-99% accuracy on footage1.mov

## [2026-02-10] UX: State Naming (User Feedback)
- User pointed out: "DISTRACTED" is wrong wording for cleaning table before studying. You're not distracted FROM anything — you're just not studying yet.
- "Wording matters" — especially for a kid-facing product. Don't guilt-trip kids for doing normal things.
- FUTURE: Consider renaming DISTRACTED → "NOT STUDYING" or "IDLE" or "OTHER" for the product UX
- FOR NOW: Keep "DISTRACTED" in eval ground truth as the comparison target. The system just needs to NOT say SLOUCHING for non-seated activities.
- The detection logic stays the same — this is purely a labeling/UX rename that can be done later without changing thresholds.

## [2026-02-10] Pre-Calibration Behavior
- When calibration hasn't completed, system should NOT default to SLOUCHING
- Standing/moving person = not studying, but NOT slouching
- Fix: Skip posture voting until calibration has a baseline, rely on MoViNet + phone only
