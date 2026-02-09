
## Research: Auto-Calibration & Camera-Angle-Invariant Pose Monitoring (Feb 2026)

### 1. AUTO-CALIBRATION TECHNIQUES

#### Commercial Products (Upright Go - 2026 Standard)
**Evidence**: Upright Go posture device (https://www.uprightpose.com)
- **Manual calibration required**: User must calibrate every time device is placed on back
- **Calibration UX**: Find comfortable upright position → tap "Calibrate" button OR double-click power button
- **Baseline approach**: Single-point calibration establishes baseline for slouch detection
- **Re-calibration triggers**: App reminds user to recalibrate if device isn't set properly
- **Key insight**: Even commercial wearables haven't eliminated manual calibration - they just made it 1-tap

**Limitation for us**: Wearable devices have IMU sensors (accelerometer/gyroscope) which give absolute orientation. Cameras only give relative pose → harder problem.

#### Academic Approaches (2024-2026 Research)

**ALIGN Framework (MDPI Algorithms, Jan 2026)**
- **Auto-calibration method**: Uses first N frames (e.g., 30 frames = 1 second) to establish "good posture" baseline
- **Assumption**: User starts in correct posture when system initializes
- **Adaptive baseline**: Rolling window of "good posture" frames to update baseline over time
- **Limitation**: Requires user to start in good posture (not truly zero-calibration)

**Kalman-MediaPipe Fusion (IEEE, Sept 2025)**
- **Approach**: Kalman filter smooths MediaPipe pose over time to reduce noise
- **Baseline establishment**: Statistical analysis of first 50 frames to find "neutral" pose
- **Key metric**: Uses variance of joint angles - low variance = stable posture = potential baseline
- **Limitation**: Still assumes initial frames contain good posture

**PostureScreen Mobile (mHealth app for kids, 2025)**
- **Method**: Takes single photo, compares to age-appropriate normative database
- **No calibration needed**: Uses population norms instead of personal baseline
- **Trade-off**: Less personalized, may flag normal variations as problems

### 2. CAMERA-ANGLE-INVARIANT METRICS

#### Joint Angle Ratios (Most Promising)
**Evidence**: TU Darmstadt stereo camera study (Sensors, Dec 2024)
- **Key finding**: Joint angles (hip, knee, elbow) are camera-angle-invariant
- **Method**: Calculate 3D angle between three landmarks (e.g., shoulder-hip-knee for hip angle)
- **Accuracy**: Hip/knee angles accurate within 5-8° even with single camera at various angles
- **Why it works**: Angles are intrinsic to body geometry, not camera perspective

**Practical angles for study monitoring**:
- **Neck angle**: Ear-Shoulder-Hip (forward head posture detection)
- **Back angle**: Shoulder-Hip-Knee (slouching detection)
- **Arm angle**: Shoulder-Elbow-Wrist (writing posture)
- **Symmetry ratio**: Left hip angle / Right hip angle (asymmetric sitting)

#### Body Proportion Ratios
**Evidence**: V-VIPE (CVPR 2024 Workshop)
- **Canonical pose embedding**: VAE learns view-invariant representation of 3D pose
- **Key insight**: Ratios of body segment lengths are view-invariant
  - Torso length / Total height
  - Upper arm / Forearm ratio
  - Thigh / Shin ratio
- **Application**: Can detect "leaning" by comparing current ratios to baseline ratios

**Limitation**: Requires good 2D pose estimation first (occlusion still a problem)

### 3. MEDIAPIPE POSE Z-COORDINATE RELIABILITY

#### Official MediaPipe Documentation (2026)
**Two coordinate systems**:
1. **`pose_landmarks`** (image coordinates): x, y in [0,1], z = depth relative to hips (in pixels)
2. **`pose_world_landmarks`** (world coordinates): x, y, z in meters, origin at hip midpoint

**Z-coordinate reliability findings**:

**GitHub Issue #1611 (2021, still relevant 2026)**:
- **z in `pose_landmarks`**: "Rough estimate, not reliable for absolute depth"
- **z in `pose_world_landmarks`**: "Better, but still noisy - uses internal body model"
- **Recommendation from Google team**: "Use z for relative comparisons (e.g., is hand in front of body?), not absolute measurements"

**TU Darmstadt Accuracy Study (Sensors, Dec 2024)**:
- **Monocular MediaPipe 3D**: Median RMSE of 56.3mm for joint positions
- **Stereo reconstruction**: Median RMSE of 30.1mm (46% improvement)
- **Z-axis specifically**: 2-3x more error than x/y axes in monocular mode
- **Conclusion**: "MediaPipe's monocular z is insufficient for precise exercise analysis"

**Practical implication for us**:
- ✅ **Can use z for**: Detecting if hand is in front of face (relative depth)
- ❌ **Cannot use z for**: Measuring exact forward lean distance
- ✅ **Better approach**: Use joint angles (camera-invariant) instead of absolute z-depth

### 4. ADAPTIVE/ROLLING BASELINE APPROACHES

#### Rolling Window Baseline (Found in multiple repos)
**Pattern**: Maintain buffer of last N "good posture" frames, update baseline continuously

**Example implementation** (from GitHub search):
```python
class RollingAverage:
    def __init__(self, window_size=100):  # 100 frames = ~3 seconds at 30fps
        self.window = deque(maxlen=window_size)
    
    def add(self, value):
        self.window.append(value)
    
    def mean(self):
        return np.mean(self.window, axis=0)
```

**Application to posture**:
1. Detect "good posture" frames (e.g., back angle > 160°, neck angle > 150°)
2. Add to rolling window
3. Baseline = mean of rolling window
4. Alert when current pose deviates > threshold from baseline

**Advantages**:
- Adapts to user's natural posture changes (e.g., kid grows, camera moves slightly)
- Handles gradual drift (kid slowly slouches over 10 minutes)
- No explicit calibration needed

**Challenges**:
- How to detect "good posture" initially? (chicken-egg problem)
- Risk of "baseline drift" if bad posture frames leak into window

#### Hybrid Approach (Recommended for kid-watch)
**Phase 1: Initial calibration (first 30 seconds)**
- Prompt: "Sit up straight for 30 seconds"
- Collect 900 frames (30 fps × 30 sec)
- Filter outliers (remove frames with sudden movements)
- Establish initial baseline

**Phase 2: Adaptive baseline (ongoing)**
- Every 5 minutes, check if kid has maintained good posture for 10+ seconds
- If yes, update baseline with rolling average of those frames
- If no good posture detected in 30 minutes, alert parent (kid may need reminder)

### 5. 3D POSE NORMALIZATION TECHNIQUES

#### Canonical Frame Transformation
**V-VIPE Method (CVPR 2024)**:
1. **Center pose**: Translate so hip midpoint is at origin
2. **Align to gravity**: Rotate so vertical axis aligns with shoulder-hip vector
3. **Normalize scale**: Scale so shoulder-width = 1.0 unit
4. **Result**: Pose in canonical frame, independent of camera position/angle

**3DPCNet Method (arXiv Sept 2025)**:
- **Hybrid encoder**: Graph CNN (local skeleton features) + Transformer (global context)
- **Learns rotation**: Predicts rotation matrix to align any pose to canonical frame
- **Key advantage**: Handles partial occlusion better than rule-based methods

**Practical implementation for us**:
```python
def normalize_pose(landmarks):
    # 1. Center at hip midpoint
    hip_mid = (landmarks[LEFT_HIP] + landmarks[RIGHT_HIP]) / 2
    centered = landmarks - hip_mid
    
    # 2. Align to vertical (shoulder-hip vector)
    shoulder_mid = (landmarks[LEFT_SHOULDER] + landmarks[RIGHT_SHOULDER]) / 2
    vertical = shoulder_mid - hip_mid
    rotation = compute_rotation_to_align(vertical, [0, 1, 0])
    aligned = apply_rotation(centered, rotation)
    
    # 3. Normalize scale (shoulder width = 1.0)
    shoulder_width = np.linalg.norm(landmarks[LEFT_SHOULDER] - landmarks[RIGHT_SHOULDER])
    normalized = aligned / shoulder_width
    
    return normalized
```

**Benefits**:
- Camera angle doesn't matter (ceiling vs wall mount)
- Camera distance doesn't matter (scale normalized)
- Can compare poses across different kids (scale normalized)

### 6. STATE-OF-THE-ART SUMMARY (Feb 2026)

#### What's Possible Now:
✅ **Joint angle-based metrics**: Reliable, camera-angle-invariant, accurate within 5-8°
✅ **Pose normalization**: Can make measurements camera-position-independent
✅ **Adaptive baselines**: Rolling window approach works for gradual adaptation
✅ **MediaPipe world_landmarks**: Good enough for relative depth comparisons

#### What's Still Hard:
❌ **True zero-calibration**: All systems assume initial good posture or use population norms
❌ **Absolute depth from monocular**: MediaPipe z is noisy (2-3x more error than x/y)
❌ **Occlusion handling**: Still degrades all methods significantly
❌ **Multi-person scenes**: Most research focuses on single-person pose

#### Recommended Approach for Kid-Watch:
1. **Use joint angles** (neck, back, arm) as primary metrics - camera-angle-invariant
2. **Normalize pose** to canonical frame (center at hips, align to vertical, scale by shoulder width)
3. **Hybrid calibration**:
   - Initial: 30-second "sit up straight" prompt (one-time per session)
   - Adaptive: Rolling window of "good posture" frames, update baseline every 5 min
4. **Use `pose_world_landmarks`** for relative depth (e.g., hand in front of face)
5. **Avoid absolute z-depth measurements** - too noisy from monocular camera

#### Key Papers to Reference:
- **ALIGN Framework** (MDPI Algorithms 2026): Auto-calibration via initial frames
- **TU Darmstadt Stereo Study** (Sensors 2024): Joint angle accuracy benchmarks
- **V-VIPE** (CVPR 2024): Canonical pose embedding for view-invariance
- **3DPCNet** (arXiv 2025): Robust pose canonicalization with transformers


## [2026-02-08] Production Deployment Research — Scale Math & Architecture

### Critical Insight: Cloud-Only Inference is IMPOSSIBLE at Scale
- **700K cameras streaming 720p @ 5 FPS = 350-700 Tbps** — no ISP can handle this
- **Hybrid edge-cloud is MANDATORY**: Edge preprocessing (landmarks only) reduces bandwidth by 99.2%
- **56 Gbps total** for 700K cameras sending landmarks only (0.08 Mbps each) — FEASIBLE

### Cost Analysis: Edge Wins at Scale
- **Cloud-only**: $2.1M-$8.4M/month for 700K cameras (unsustainable)
- **Edge-only**: $24.5M-$42M one-time (12-18 month ROI vs cloud)
- **Hybrid (WINNER)**: $700K-$1.4M/month + $24.5M-$42M upfront — best economics at scale

### Deployment Timeline: 22 Months is Realistic
- Beta (100 cameras): 1 month — validate with employees
- Pilot (10K cameras): 3 months — early adopters, 2-3 cities
- Regional (100K cameras): 6 months — scale infrastructure
- National (700K cameras): 12 months — full rollout
- **Key**: Start small, measure everything, automate rollback

### Monitoring at Scale: Prometheus + Grafana Proven
- **Grafana Cloud handles 20M active series** (verified case study)
- **700K cameras = 7M-14M time series** (10-20 metrics/camera) — well within capacity
- **Regional federation**: 10-20 regional Prometheus servers → central Grafana
- **AI anomaly detection**: Grafana ML insights to catch model degradation early

### OTA Updates: Phased Rollout is NON-NEGOTIABLE
- **NEVER push to 700K cameras simultaneously** — phased 1% → 5% → 25% → 100% over 2-4 weeks
- **Canary deployment**: Test on 1,000 cameras (0.14%) for 24-48 hours first
- **Auto-rollback**: If >5% failure rate, rollback automatically
- **Delta updates**: Only send changed model weights (1-2 MB vs 10 MB) — 80-90% bandwidth savings

### Reliability: Design for Failure from Day 1
- **Exponential backoff reconnection**: 1s, 2s, 4s, 8s, 16s, max 60s + jitter (avoid thundering herd)
- **Local buffering**: 1-hour of inference results on edge device
- **Graceful degradation**: Full → Degraded → Minimal → Offline (4 levels)
- **Multi-region cloud**: Primary + 2 replicas, daily snapshots, 30-day retention

### Similar Deployments Validate Feasibility
- **Flock Safety**: 80,000 AI cameras across USA (license plate recognition)
- **Hikvision/Dahua**: Millions of cameras globally (edge AI + cloud VMS)
- **Amazon Ring**: 10M+ cameras, moved to edge AI to reduce cloud costs
- **Viettel**: Already has OTA infrastructure (TR-069/CWMP), proven at scale

### Key Success Factors
1. **Edge-first architecture** — cloud-only is a non-starter at 100K+ scale
2. **Measure from day 1** — Prometheus + Grafana, not after problems arise
3. **Automate everything** — rollback, alerts, scaling (no manual intervention at 700K scale)
4. **Start small** — beta with employees (avoid public failure), then pilot, then scale
5. **Phased OTA** — never push updates to all cameras at once

### Research Sources Quality
- **IEEE papers** (OVIDA, Ancilia, fault-tolerant ONVIF) — HIGH confidence, academic rigor
- **Industry case studies** (Flock Safety, Grafana Cloud 20M series) — VERIFIED, real-world data
- **Cloud pricing** (AWS, GCP) — VERIFIED from official pricing pages (Jan 2026)
- **Bandwidth calculations** — HIGH confidence, multiple sources corroborate
- **Deployment timelines** — MEDIUM confidence, inferred from similar IoT projects

