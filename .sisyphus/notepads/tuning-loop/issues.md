# Tuning Loop Issues

## [2026-02-10] Known Risks
- Pipeline has never been run end-to-end on video — may crash
- Gemini analyzer script timed out on first attempt — may need debugging
- MoViNet model loading can be slow (~30s)
- 53K frames at 30fps = potentially long processing time

## [2026-02-10] CRITICAL: Uncalibrated Posture Defaults to SLOUCHING (User Feedback)
- **Problem**: First 5-7 minutes of footage1.mov, user is cleaning table (standing up, moving around)
- Ears are out of frame → shoulder_hip fallback mode → calibration never completes → posture defaults to "bad" → state machine says SLOUCHING
- **But SLOUCHING is WRONG**: User is standing up cleaning — that's DISTRACTED, not SLOUCHING
- Slouching requires the person to be SEATED and slumped. Standing/moving is a different activity entirely.
- **Root cause**: When calibration hasn't completed, the system treats "uncalibrated posture" as "bad posture" which triggers SLOUCHING state
- **Fix needed**: When calibration hasn't completed yet, either:
  - (A) Fall back to MoViNet-only detection (skip posture entirely until calibrated)
  - (B) Recognize standing/moving = DISTRACTED based on action classifier
  - (C) Don't let posture component vote SLOUCHING until calibration has a baseline
- **User note**: "If in doubt, use Gemini 3 Flash Preview to check what's actually happening"

## [2026-02-10] Camera Angle: Left Side, Ears Visibility
- Camera is on LEFT side of person
- When seated: left ear SHOULD be visible to camera
- When STANDING UP: ears may go out of frame (person is taller, camera aimed at desk level)
- This is expected behavior for side-camera setup — the system just needs to handle it gracefully
