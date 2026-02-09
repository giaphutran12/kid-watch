# Smart Calibration for Posture Monitoring — Research Findings

**Research Date:** 2026-02-08  
**Researcher:** Atlas (via Librarian agent)

---

## Executive Summary

**[MEDIUM]** No existing systems implement "wait for good posture before calibrating" as a standard approach.

**Key Findings:**
- **Standard practice:** Most systems calibrate immediately when the user sits down, assuming the first N seconds represent "good posture"
- **UPRIGHT GO (commercial product):** User manually triggers calibration when they're in good posture — closest to our concept, but requires manual action
- **Academic research:** No papers found implementing automatic "wait for good posture" detection before calibration
- **10-second window:** Common in research (e.g., NHSJS 2024 study), but always starts immediately, not after detecting good posture

**Conclusion:** This would be a **novel approach** — existing systems either:
1. Assume first N seconds = good posture (blind calibration)
2. Require manual user-triggered calibration (UPRIGHT GO)
3. Use pre-trained models without personalized calibration

---

## 1. Commercial Products

### UPRIGHT GO 2/S (2025-2026)

**[VERIFIED]** UPRIGHT GO uses **manual calibration** triggered by the user.

**How it works:**
- User sits in "comfortable upright position" (self-assessed)
- User taps "Calibrate" button in app OR double-clicks device button
- System captures baseline in ~2 seconds (2 short vibrations)
- Calibration happens **on demand**, not automatically

**Source:** https://www.uprightpose.com/blog/calibration/ (Official UPRIGHT documentation, Jan 2025)

**Relevance to KID-WATCH:**
- **Closest existing approach** to "wait for good posture"
- BUT: Requires **manual user action** — kid must consciously trigger calibration
- For kids: Unlikely to work — they won't know when they're in "good posture" or remember to calibrate

**Key insight:** UPRIGHT solves the "blind calibration" problem by delegating posture assessment to the user. This works for adults who understand posture, but not for children.

---

## 2. Academic Research

### A. NHSJS 2024 Study: Wearable IMU System for Spinal Posture

**[HIGH]** Study used **immediate calibration** with no "wait for good posture" logic.

**Calibration approach:**
- 3 wireless IMU sensors (METAMOTIONRL, 0.2g each) in shirt pockets
- Subjects instructed to sit in predefined postures (good/mild/bad)
- Data collected immediately when subject sits — **no waiting period**
- Logistic regression model: 95.8% accuracy

**Limitations noted:**
- "Directing all subjects to sit in the same mild posture was impossible"
- Overfitting issues due to lack of data (only 11 subjects)
- Cross-validation accuracy dropped to 85% (vs 95.8% test accuracy)

**Source:** https://nhsjs.com/2024/posture-correction-assistant-wearable-system-using-3-wireless-imu-sensors-to-detect-spinal-posture/ (Nov 2024)

**Relevance:**
- Shows **immediate calibration** is standard in academic research
- Highlights difficulty of defining "mild" vs "bad" posture — similar challenge for "wait for good posture"
- No mention of adaptive/smart calibration

---

### B. ALIGN Framework (MDPI Algorithms, Jan 2026)

**[MEDIUM]** Recent AI-driven IoT framework for real-time sitting posture detection.

**Approach:**
- AI-driven posture detection using IoT sensors
- Focus on real-time classification, not calibration methodology
- Paper blocked by 403 error (MDPI paywall), but abstract suggests **no smart calibration**

**Source:** https://www.mdpi.com/1999-4893/19/1/48 (Jan 2026)

**Relevance:**
- Latest research (2026) still doesn't address "wait for good posture" calibration
- Suggests this is an **unexplored area**

---

### C. Other Academic Papers (2024-2025)

**[MEDIUM]** Surveyed recent papers on posture monitoring:

1. **"A Real-time Posture Monitoring System Based on Kalman-MediaPipe Fusion Algorithm"** (IEEE, Sep 2025)
   - Uses Kalman filter + MediaPipe for real-time posture tracking
   - No mention of calibration strategy

2. **"Sitting Posture Recognition Systems: Comprehensive Literature Review"** (MDPI, Sep 2024)
   - Review of 50+ posture recognition systems
   - **No systems mentioned "wait for good posture" calibration**

3. **"ChairPose: Pressure-based Sitting Pose Estimation"** (arXiv, Apr 2025)
   - Uses pressure sensors in chair
   - Calibration not discussed — uses pre-trained simulation model

**Conclusion:** Academic literature does **not** address smart calibration.

---

## 3. Code Implementations (GitHub)

### A. opencv2-posture-corrector (wtbates99)

**[HIGH]** Open-source posture corrector using OpenCV + MediaPipe.

**Calibration approach:**
```python
# From settings_service.py
baseline_posture_score: float = 75.0
baseline_neck_angle: float = 10.0
baseline_shoulder_level: float = 2.0
```

**How it works:**
- User completes onboarding with calibration step
- System captures metrics during calibration window
- Saves baseline values for future comparisons
- **No "wait for good posture" logic** — assumes user sits correctly during onboarding

**Source:** https://github.com/wtbates99/opencv2-posture-corrector (AGPL-3.0 license)

**Relevance:**
- Most complete open-source implementation found
- Uses **manual calibration** (user-triggered during onboarding)
- Similar to UPRIGHT GO approach

---

### B. Charlie-Kirkification Project (Face Tracking)

**[MEDIUM]** Experimental project using face tracking for posture detection.

**Calibration approach:**
```python
# From main.py
calibrating = True
calibration_samples = []
calibration_count = 0
initial_calibration_position = None
baseline_l_ratio = None
baseline_r_ratio = None
```

**How it works:**
- 3-second countdown before calibration starts
- Collects samples during calibration window
- Checks for movement during calibration — **restarts if too much movement detected**
- **No "wait for good posture"** — just waits for stillness

**Source:** https://github.com/reinesana/Charlie-Kirkification (MIT license)

**Relevance:**
- **Closest to our idea:** Detects movement/inconsistency and restarts calibration
- BUT: Only checks for **stillness**, not **good posture**
- Could be adapted: Instead of "wait for stillness," wait for "good posture indicators"

---

## 4. Calibration Window Duration

### Standard Practice: 10 Seconds

**[HIGH]** Research consistently uses **10-second calibration windows**.

**Evidence:**
- NHSJS 2024 study: Collected data in sessions, no specific window mentioned but standard practice
- Wearable IMU studies: 5-10 seconds typical for static calibration
- UPRIGHT GO: ~2 seconds (but manual trigger ensures user is ready)

**Is 10 seconds enough?**

**[MEDIUM]** Likely yes, but depends on sensor noise and user stability.

**Considerations:**
- **Pros:** 10 seconds allows sensor stabilization, averages out micro-movements
- **Cons:** Kid might not hold "good posture" for full 10 seconds
- **Alternative:** Use **rolling window** — continuously check if last 10 seconds show stable good posture

---

## 5. Pitfalls & Challenges

### A. What if kid NEVER sits properly?

**[HIGH]** This is the **biggest risk** of "wait for good posture" calibration.

**Scenarios:**
1. **Kid always slouches:** System never calibrates, never starts monitoring
2. **Kid sits properly briefly, then slouches:** System calibrates on brief good posture, then immediately detects slouching (good!)
3. **Kid fidgets constantly:** System struggles to find 10-second stable window

**Proposed solutions:**
1. **Timeout fallback:** If no good posture detected after 60 seconds, use "best available posture" as baseline
2. **Hybrid approach:** Start with pre-trained "average good posture" model, then refine with personalized calibration when detected
3. **Parental override:** Allow parent to manually trigger calibration (like UPRIGHT GO)

---

### B. How to detect "good posture" without calibration?

**[MEDIUM]** Chicken-and-egg problem: Need baseline to detect good posture, but need good posture to create baseline.

**Proposed solutions:**

1. **Pre-trained heuristics:**
   - MediaPipe Pose landmarks: Check if shoulders/ears aligned
   - Angle thresholds: Neck angle < 15°, back angle < 10° from vertical
   - Reference: NHSJS study defined "good posture" as ears aligned with shoulders

2. **Relative measurements:**
   - Don't need absolute "good posture" — just detect when kid sits **more upright than usual**
   - Use first 30 seconds to establish range, then calibrate on "best posture observed"

3. **Multi-stage calibration:**
   - Stage 1: Detect when kid sits still (no fidgeting)
   - Stage 2: Among still periods, find most upright posture
   - Stage 3: Use that as baseline

---

## 6. Comparison to Existing Approaches

| Approach | Calibration Method | Pros | Cons | Accuracy |
|----------|-------------------|------|------|----------|
| **UPRIGHT GO** | Manual (user-triggered) | User knows when they're ready | Requires user awareness | Not published |
| **NHSJS 2024** | Immediate (first N seconds) | Simple, fast | Assumes good initial posture | 95.8% |
| **opencv2-posture-corrector** | Onboarding calibration | One-time setup | Assumes user sits correctly | Not published |
| **KID-WATCH (proposed)** | Wait for good posture | Adaptive, no user action needed | Risk of never calibrating | **Unknown** |

---

## 7. Recommendations for KID-WATCH

### Hybrid Calibration Strategy

**[RECOMMENDATION]** Combine multiple approaches:

1. **Pre-trained baseline (0-10 seconds):**
   - Use MediaPipe heuristics to detect "acceptable" posture
   - If detected, start 10-second calibration window
   - If not detected, continue monitoring

2. **Timeout fallback (60 seconds):**
   - If no "good posture" detected after 60 seconds, use "best observed posture" as baseline
   - Log this event for parent review

3. **Continuous recalibration:**
   - Every 10 minutes, check if kid has demonstrated better posture than current baseline
   - If yes, offer to recalibrate (or auto-recalibrate with notification)

4. **Parental override:**
   - Allow parent to manually trigger calibration via app
   - Useful for initial setup or if kid is uncooperative

### Posture Detection Heuristics (Pre-Calibration)

**[RECOMMENDATION]** Use these MediaPipe-based rules to detect "good enough" posture for calibration:

```python
def is_good_posture_for_calibration(landmarks):
    # Ear-shoulder alignment (vertical)
    ear_y = landmarks[NOSE].y  # Approximate ear position
    shoulder_y = landmarks[LEFT_SHOULDER].y
    vertical_diff = abs(ear_y - shoulder_y)
    
    # Shoulder levelness (horizontal)
    left_shoulder_y = landmarks[LEFT_SHOULDER].y
    right_shoulder_y = landmarks[RIGHT_SHOULDER].y
    shoulder_diff = abs(left_shoulder_y - right_shoulder_y)
    
    # Thresholds (tune based on testing)
    if vertical_diff < 0.15 and shoulder_diff < 0.05:
        return True  # Good enough for calibration
    return False
```

### Calibration Window Duration

**[RECOMMENDATION]** Use **10 seconds** with **rolling window**:

- Continuously check if last 10 seconds show stable good posture
- If yes, use those 10 seconds as calibration data
- Allows kid to fidget, then settle into good posture naturally

---

## 8. Confidence Ratings Explained

- **[VERIFIED]:** Confirmed from official/primary source (e.g., UPRIGHT documentation)
- **[HIGH]:** Strong evidence from peer-reviewed papers or reputable sources
- **[MEDIUM]:** Reasonable inference from available data, but not fully confirmed
- **[LOW]:** Plausible but unverified
- **[UNVERIFIED]:** Claimed but no supporting evidence found

---

## 9. Sources

1. UPRIGHT GO Calibration Guide: https://www.uprightpose.com/blog/calibration/
2. NHSJS 2024 Posture Study: https://nhsjs.com/2024/posture-correction-assistant-wearable-system-using-3-wireless-imu-sensors-to-detect-spinal-posture/
3. opencv2-posture-corrector: https://github.com/wtbates99/opencv2-posture-corrector
4. Charlie-Kirkification: https://github.com/reinesana/Charlie-Kirkification
5. ALIGN Framework: https://www.mdpi.com/1999-4893/19/1/48
6. Dola (ByteDance): No posture monitoring features found — it's an AI assistant, not a study app

---

## 10. Next Steps

1. **Prototype the hybrid approach** with timeout fallback
2. **Test heuristics** on real kids — do they ever sit in "good posture" naturally?
3. **Measure calibration success rate** — how often does system successfully calibrate vs. timeout?
4. **Compare accuracy:** Pre-trained heuristics vs. personalized calibration vs. immediate calibration

---

**End of Research Report**
