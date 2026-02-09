# v0.3.2 Video Testing - Learnings

## [2026-02-09] TimeProvider Abstraction Implementation

### Pattern: Dependency Injection for Time
Created `TimeProvider` abstract base class to enable deterministic time handling in video replay mode while maintaining real-time behavior in live mode.

**Key Design Decisions:**
1. **ABC Pattern**: Used `abc.ABC` and `@abc.abstractmethod` for enforcing interface contract
2. **Dual Implementation Strategy**:
   - `RealTime`: Wraps `time.time()`, `tick()` is no-op (system clock advances automatically)
   - `VideoTime`: Frame-based virtual time with two advancement modes:
     - Preferred: Extract timestamp from `cv2.CAP_PROP_POS_MSEC` (actual frame metadata)
     - Fallback: Increment by `1/fps` (deterministic, no video dependency)

3. **Conditional cv2 Import**: Import `cv2` only inside `tick()` method to avoid import errors in test environments where cv2 may not be available

4. **Logging with [VIDEO-TEST] Tag**: All time advancement operations log with `[VIDEO-TEST]` prefix for easy filtering during video replay debugging

### Integration Pattern for Consumers
Each component that uses `time.time()` will be refactored to accept optional `time_provider` parameter:
```python
def __init__(self, ..., time_provider=None):
    self.clock = time_provider or RealTime()

# Replace: current_time = time.time()
# With:    current_time = self.clock.now()
```

### Verification
- ✅ File created: `kid_watch/time_provider.py`
- ✅ Imports work: `from kid_watch.time_provider import RealTime, VideoTime`
- ✅ RealTime.now() returns float (system time)
- ✅ VideoTime.now() returns float (virtual time)
- ✅ VideoTime.tick() advances time correctly
- ✅ VideoTime.reset() resets to 0.0
- ✅ Type hints on all methods
- ✅ Module docstring explains purpose

### Next Steps
1. Inject `TimeProvider` into components that call `time.time()`:
    - `kid_watch/detectors/movinet_detector.py` (state resets, disagreement timing)
    - `kid_watch/calibration.py` (calibration state machine, ~10 occurrences)
    - `kid_watch/engagement.py` (hysteresis timers)
    - `kid_watch/detectors/posture_detector_yolo.py` (slouch timing)
    - `kid_watch/detectors/study_detector.py` (observation timers)
    - `kid_watch.py` (FPS calculation)

2. Create video replay test harness that:
    - Loads pre-recorded video
    - Creates `VideoTime(fps=30.0)` instance
    - Passes it to all components
    - Verifies deterministic behavior across multiple runs

## [2026-02-09] Scenario Module Implementation

### What Was Built
Created `kid_watch/eval/scenario.py` — a YAML/JSON scenario parser for defining expected detection states over time ranges in videos.

**Files Created:**
- `kid_watch/eval/__init__.py` — Module exports
- `kid_watch/eval/scenario.py` — Core scenario parsing logic (9.9 KB)

### Key Design Decisions

#### 1. Time Parsing Flexibility
Implemented `parse_time()` to handle multiple formats:
- `"M:SS"` → `"2:30"` = 150 seconds
- `"H:MM:SS"` → `"1:05:30"` = 3930 seconds  
- Raw numeric → `90` or `90.5` = 90.0 or 90.5 seconds

This flexibility allows scenario authors to use whatever format is most natural.

#### 2. YAML + JSON Support with Graceful Fallback
- **Primary:** PyYAML for `.yaml`/`.yml` files (human-friendly)
- **Fallback:** JSON parsing if PyYAML not installed
- **Rationale:** JSON is stdlib-available; YAML is optional but preferred for readability

PyYAML is NOT in requirements.txt, so the module gracefully degrades to JSON-only if not installed.

#### 3. Dataclass-Based Design
Used `@dataclass` for `Segment` and `Scenario`:
- Type hints on all fields
- Validation in `__post_init__`
- Clean, immutable API

#### 4. Validation Strategy
- **Segment validation:** Checks `end > start`, warns on unknown states
- **Scenario validation:** Checks for overlapping segments, sorts by start time
- **File validation:** Checks required fields (`video`, `segments`), provides clear error messages

All validation includes `[EVAL]` prefix for easy log filtering.

#### 5. Boundary Semantics
Segments use half-open intervals: `[start, end)`
- `segment.contains(time)` returns `True` if `start <= time < end`
- This prevents ambiguity at segment boundaries
- Example: Two consecutive segments `[0, 100)` and `[100, 200)` don't overlap

### API Design

```python
# Load scenario
scenario = load_scenario("scenarios/study_session_01.json")

# Query expected state at a timestamp
expected = scenario.get_expected_state(time_seconds=75.0)  # → "STUDYING"

# Get full segment info
segment = scenario.get_segment_at(time_seconds=75.0)
print(segment.label)  # → "Normal studying at desk"

# Access metadata
print(scenario.metadata["recorded_by"])  # → "Edward"
```

### Valid States
```python
VALID_STATES = {
    "STUDYING",      # Normal studying posture
    "SLOUCHING",     # Poor posture
    "DISTRACTED",    # Not focused on desk
    "WARNING",       # Intermediate warning state
    "ABSENT",        # Person left frame
    "CALIBRATING",   # System calibrating
    "UNKNOWN"        # Unknown state
}
```

### Testing Coverage
✅ Time parsing (M:SS, H:MM:SS, numeric)
✅ Segment validation (range checks, state validation)
✅ Scenario loading (JSON, YAML with fallback)
✅ Boundary conditions (half-open intervals)
✅ Metadata preservation
✅ Overlap detection and warnings
✅ Unknown state warnings

### Integration with Evaluator
The `evaluator.py` module (already in place) will use this scenario parser:
```python
from kid_watch.eval.scenario import load_scenario

scenario = load_scenario("scenarios/study_session_01.json")

# In main loop:
for frame in video:
    expected = scenario.get_expected_state(frame.time_seconds)
    actual = pipeline.detect(frame)
    evaluator.record(frame.time_seconds, expected, actual)
```
