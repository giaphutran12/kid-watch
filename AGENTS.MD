## Project Context

- **Current date:** February 2026
- **Project:** KID-WATCH — Real-time study monitoring system for Viettel (700k home cameras in Vietnam)
- **Stack:** Python 3.13 (app) + Python 3.12 (ML pipeline, TensorFlow), MediaPipe (Pose + Face Landmarker), YOLOv8n, OpenCV, NumPy, MoViNet-A2 (TensorFlow)
- **Vision:** Enterprise-grade, commercial product targeting hundreds of thousands to millions of users
- **Founder context:** First-time ML practitioner, eager to learn. Explain ML concepts clearly but never compromise on production quality. This is NOT a learning project — it's a real startup building for massive scale. Treat every decision as if 700K cameras depend on it.

## Atlas Agent — Token Efficiency Rule (CRITICAL)

**Atlas (the orchestrator) must NEVER do manual work that costs more tokens than delegating.**

- Atlas is a conductor, not a musician. It delegates, coordinates, and verifies.
- If a task requires reading multiple files, searching codebases, writing code, or doing deep analysis — **delegate it to a subagent**.
- Atlas should only use tools directly for: quick verification (lsp_diagnostics, short file reads), collecting background results, managing todos, and coordinating.
- **The test:** If doing something yourself would consume more tokens than sending a prompt to a subagent and reading their response, you MUST delegate instead.
- Never fire raw tool calls (grep, glob, webfetch, web search, etc.) in bulk when a single `delegate_task()` to an explore/librarian/oracle agent would accomplish the same thing more efficiently.
- Exception: Quick single-tool calls for verification after a delegation completes are fine.

## Research Protocol (NON-NEGOTIABLE)

### Rule 1: Check Before You Search

**Before launching ANY research task, you MUST first check existing research files.**

1. Read `research_findings/` directory — glob for all `.md` files
2. Delegate an explore agent to scan existing research and report what's already been covered
3. Only research what's genuinely NEW — never re-research something already documented
4. If a finding exists but is low-confidence, you may re-verify — but note you're doing so

**The workflow:**
```
User asks research question
  → Check research_findings/*.md FIRST
  → Delegate explore agent: "What do we already know about X?"
  → Identify gaps only
  → Research ONLY the gaps
  → Append new findings to research files (never overwrite)
```

### Rule 2: Confidence Ratings Are Mandatory

**Every research finding MUST include a confidence rating:**

| Rating | Meaning | When to Use |
|--------|---------|-------------|
| `[VERIFIED]` | Confirmed from official/primary source | Official docs, APIs tested, first-party data |
| `[HIGH]` | Strong evidence from reliable sources | Reputable news, peer-reviewed papers, multiple corroborating sources |
| `[MEDIUM]` | Reasonable evidence but not fully confirmed | Single news source, blog posts, community reports |
| `[LOW]` | Plausible but unverified | Inferred from indirect data, estimates, extrapolations |
| `[UNVERIFIED]` | Claimed but no supporting evidence found | Numbers from conversation, unconfirmed claims |

**Format for every finding:**
```
**[CONFIDENCE: HIGH]** Vietnam imports 3.2M cameras/year, 96.3% from China
Source: VnExpress, citing Ministry of Information data (Aug 2024)
```

**If you can't determine confidence, mark it `[UNVERIFIED]` — never leave it unmarked.**

### Rule 3: Research Files Are Append-Only

- Never overwrite existing research — always append
- New findings go under a dated section header: `## [YYYY-MM-DD] Topic`
- Corrections to existing findings go under: `### Correction: [original claim]`

### Rule 4: Audit Trail — Where Everything Lives

All project knowledge has a designated home. Always check before creating, always document after discovering.

| What | Where | Format |
|------|-------|--------|
| Research findings | `research_findings/*.md` | Append-only, confidence-rated, sourced |
| Implementation decisions | `.sisyphus/notepads/{plan}/decisions.md` | Append-only, timestamped |
| Technical learnings | `.sisyphus/notepads/{plan}/learnings.md` | Append-only, patterns & conventions |
| Known issues & gotchas | `.sisyphus/notepads/{plan}/issues.md` | Append-only, with workarounds |
| Implementation plans | `.sisyphus/plans/*.md` | Read-only (orchestrator manages) |
| Agent rules & project context | `AGENTS.md` | This file — project-level rules |

## Background Task Handling

**NEVER poll for background task results.** Use `block=true` with generous timeouts, or wait for the system notification that a task completed. When the user sends a new message, prioritize reading and responding to it immediately — do not be stuck in a polling loop.

- Launch background agents with `run_in_background=true`
- Wait for system `[BACKGROUND TASK COMPLETED]` notifications
- Only call `background_output` after receiving the completion notification
- If you need results before proceeding, use `block=true` with `timeout=300000` (5 min) — but prefer non-blocking when possible
- When the user sends a message while tasks are running, respond to the user FIRST, then collect results

## Delegation Protocol

- Always use `delegate_task()` for implementation work
- One task per delegation — never batch multiple tasks
- Use `session_id` for retries and follow-ups (preserves context, saves tokens)
- Store every `session_id` returned from delegations
- **`run_in_background=true` ALWAYS. No exceptions. Never set `run_in_background=false` — every `delegate_task()` call runs in background so Atlas stays productive.**

