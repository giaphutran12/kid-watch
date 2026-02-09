# Break Detection & Standing Behavior Research

## [2026-02-08] Break Detection & Standing Behavior Research

### Section 1: Dola (ByteDance) Break Handling

**[MEDIUM]** Dola monitors posture, concentration, and attention level. ~172M users in China. Parents leave phone on desk.
- Source: The News (Pakistan), Jan 14, 2026

**[LOW]** No specific break handling documentation found in English-language sources. Dola appears to be primarily an AI tutoring assistant with posture monitoring.
- Source: Limited English documentation available

---

### Section 2: Pomodoro in Study Monitoring

**[HIGH]** Pomodoro technique widely used in study apps (Focus Booster, Tomatoma), but ALL are manual timers, NOT camera-based AI detection.
- Source: App Store listings, market research

**[MEDIUM]** Tomatoma uses AI to auto-pause when focus breaks — "AI automatically tracks your pure focus time."
- Source: App Store listing, 2026

**[HIGH]** No camera-based Pomodoro apps found that distinguish "break" from "distraction" — this is an unsolved UX problem.
- Source: Comprehensive app store and GitHub search

---

### Section 3: Standing Detection in Posture Monitoring

**[VERIFIED]** UPRIGHT GO uses "Training Mode" (vibrates on slouch) and "Tracking Mode" (logs only). User must manually switch modes. No automatic standing detection.
- Source: uprightpose.com

**[HIGH]** Desktop posture apps (SitApp, PostureFix, SlouchSniper) pause monitoring when user leaves webcam frame. No distinction between "standing at desk" vs "left the room."
- Source: App Store listings and GitHub repositories

**[HIGH]** No commercial posture apps found that auto-detect standing vs sitting.
- Source: Comprehensive market research across app stores and open-source projects

---

### Section 4: Pediatric Study Break Guidelines

**[VERIFIED]** 5-minute breaks improve focus and learning outcomes. Children who took 5-min breaks after difficult math performed better on subsequent problems.
- Source: Educational and Developmental Psychologist study, cited by Mental Health Center Kids (2025)

**[VERIFIED]** Short physical activity breaks (5-10 min) during class increase time spent on-task and improve physical activity levels.
- Source: Research Quarterly for Exercise and Sport (2023), Community Preventive Services Task Force (2025)

**[HIGH]** Elementary students spend over 50% of class time distracted.
- Source: Karrie Godwin et al., 2016 study (cited by Edutopia, 2018)

**[VERIFIED]** Canadian 24-Hour Movement Guidelines: 60 min/day moderate-to-vigorous activity, no more than 2 hrs/day recreational screen time, break up long sitting periods "as often as possible."
- Source: Canadian Society for Exercise Physiology, 2025

---

### Section 5: Break Classification Framework

**[UNVERIFIED]** Proposed classification (no existing standard found):

| Break Type | Duration | Behavior | Recommended Action |
|------------|----------|----------|-------------------|
| Micro-break | 20-30 sec | Look away, shift position | Continue session |
| Short break | 1-3 min | Stand, stretch | Encourage, don't penalize |
| Medium break | 3-5 min | Bathroom, water | Pause session, auto-resume |
| Long break | 5-15 min | Left room | Pause session, require manual resume |
| Session end | >15 min | Not returned | End session, log total study time |

---

### Section 6: Standing Detection with MediaPipe

**[VERIFIED]** MediaPipe Pose provides 33 3D landmarks including hips (23, 24), knees (25, 26), ankles (27, 28). Each has x, y (normalized 0-1), z (depth), visibility.
- Source: Google AI Edge MediaPipe docs

**[HIGH]** Standing detection is trivial with hip-knee-ankle angle: sitting ≈ 90° (bent leg), standing ≈ 180° (straight leg). Found in multiple GitHub repos (fitness AI trainers, posture detection).
- Source: Multiple GitHub repositories with fitness AI and posture detection implementations

**[HIGH]** Shoulder Y-position alone is unreliable for standing detection — use relative landmark positions (hip-to-knee ratio) instead of absolute Y-coordinates.
- Source: GitHub posture detection projects and MediaPipe community discussions

**[MEDIUM]** Visibility score (0-1 per landmark) can detect "left the frame" — when nose/shoulder visibility drops below 0.5, user is likely not visible.
- Source: MediaPipe Pose documentation and practical implementations

---

### Section 7: Key Gaps & Novel Opportunities

**[UNVERIFIED]** No existing study monitoring app publicly documents break handling behavior.
- Implication: KID-WATCH has opportunity to define best practices

**[UNVERIFIED]** No camera-based app distinguishes "healthy break" from "distraction."
- Implication: This is a novel UX problem with no established solution

**[UNVERIFIED]** Standing detection is technically trivial but not implemented in commercial products.
- Implication: Market gap despite technical feasibility

**[UNVERIFIED]** KID-WATCH would be first to implement automatic break classification in a camera-based study monitor.
- Implication: Competitive advantage and research contribution

---

### Section 8: Codebase Readiness

**[VERIFIED]** PostureDetector already extracts hip landmarks (23, 24) and knee landmarks (25, 26) — no new landmark extraction needed.
- Source: KID-WATCH codebase review

**[VERIFIED]** EngagementEngine has no "break" or "pause" concept yet — only session_active boolean and engagement states (STUDYING/WARNING/DISTRACTED).
- Source: KID-WATCH codebase review

**[VERIFIED]** Position change Y-threshold is 0.45 (45% of face width) — standing up would trigger this, which needs to be handled as "break" not "recalibration."
- Source: KID-WATCH codebase review

---

## Implementation Recommendations

1. **Immediate**: Add standing detection to PostureDetector using hip-knee-ankle angle calculation
2. **Phase 1**: Implement micro-break detection (20-30 sec standing) without pausing session
3. **Phase 2**: Implement medium-break detection (3-5 min) with auto-pause and resume
4. **Phase 3**: Implement long-break detection (5-15 min) with manual resume requirement
5. **Phase 4**: Distinguish "healthy break" from "distraction" using break duration + posture patterns

---

## Research Methodology Notes

- Web search via Exa (news, app stores, documentation)
- GitHub search for open-source implementations
- Official documentation (MediaPipe, UPRIGHT GO, Canadian guidelines)
- Academic sources (Educational and Developmental Psychologist, Research Quarterly for Exercise and Sport)
- Confidence ratings assigned per AGENTS.md Rule 2
- All findings sourced and dated for future verification
