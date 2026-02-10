# Tuning Loop Decisions

## [2026-02-10] Strategy
- Run baseline first, then analyze failure patterns before changing anything
- Commit each iteration for rollback
- Use Gemini 3 Flash Preview for ambiguous frames
- Target: 98-99% accuracy on footage1.mov

## [2026-02-10] UX: State Naming (User Feedback) — SUPERSEDED by Session Model below

## [2026-02-10] Pre-Calibration Behavior
- When calibration hasn't completed, system should NOT default to SLOUCHING
- Standing/moving person = not studying, but NOT slouching
- Fix: Skip posture voting until calibration has a baseline, rely on MoViNet + phone only

## [2026-02-10] PRODUCT DESIGN: Session Model (User Decision — FINAL)

### Core Concept: Same action = different state depending on session context

**Two modes:**

1. **NO SESSION ACTIVE** (pre-session)
   - Anything the kid does = NOT_STUDYING (neutral, no judgment)
   - Cleaning, phone, sleeping — all fine
   - AWAY = not in frame (neutral)

2. **SESSION ACTIVE** (studying time)
   - STUDYING = actively studying (good)
   - SLOUCHING = studying but bad posture (warning)
   - DISTRACTED = anything other than studying, with sub-reason:
     - DISTRACTED — AWAY (not at desk)
     - DISTRACTED — PHONE (using phone)
     - DISTRACTED — OTHER (cleaning, etc.)
   - Parent sees exactly WHY the kid is distracted

### Session Triggers
- **Auto-detect**: First sustained studying (~30s) = session starts
- **Scheduled** (future): Parent sets time (e.g., 7 PM). If kid not studying at 7 PM → DISTRACTED
  - At 6:55 PM cleaning = NOT_STUDYING (fine, session hasn't started)
  - At 7:00 PM cleaning = DISTRACTED — OTHER (session started, should be studying)

### Session End (TBD — user still thinking)
- AWAY or DISTRACTED for 15+ minutes continuously → session ends
- Details TBD

### Design Principles (verbatim from user)
- "Clean the table cleanly first, then go study. That's counted as not studying, then study."
- "Distracted is whenever I go clean a table DURING my session"
- "Being on the phone or doing anything else other than studying is called distracted" (during session)
- "So the parent knows exactly what the kid is doing"
- "It's collaborative and super honest"

### Parent Dashboard — What the Parent Sees
When it's 7 PM (session time) and the kid is NOT studying, parent needs to know WHY:
- "7:00 PM — DISTRACTED: AWAY" → kid isn't even at the desk
- "7:00 PM — DISTRACTED: PHONE" → kid is at desk but on their phone
- "7:00 PM — DISTRACTED: OTHER" → kid is at desk but not studying (cleaning, fidgeting, etc.)

The system ALWAYS tells the parent what the kid is doing during session time.
Three possible reasons, no more: AWAY, PHONE, or OTHER (not studying).

### UI Display (Live Camera View)
The distraction sub-reason MUST show on the live UI overlay too, not just in reports.
When session is active and kid isn't studying, the dashboard shows:
- Status: "DISTRACTED — AWAY" (red)
- Status: "DISTRACTED — PHONE" (red)
- Status: "DISTRACTED — NOT STUDYING" (red)
Parent sees it in real-time on the camera feed, not just after the fact.

### Impact on Eval System
- footage1.json needs updating: first ~7 min cleaning = NOT_STUDYING, then session starts
- State machine needs session-aware logic
- Sub-reason tracking needed (PHONE, AWAY, OTHER)
