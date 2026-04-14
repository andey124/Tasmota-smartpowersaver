# TASKS

Status legend:
- `TODO` = not started
- `IN_PROGRESS` = currently being implemented
- `BLOCKED` = waiting on input/dependency
- `DONE` = implemented and validated

## Phase 1 - MVP Manual Override + Scheduled Off

### P1-01 Service scaffold and runtime layout
- Status: `DONE`
- Scope:
  - Create Python package layout for `desk-power-guardian`.
  - Add config loading from env and typed settings object.
  - Add app entrypoint and minimal health route.
- Deliverable:
  - Runnable service with `GET /health` returning `ok` and loaded mode (`dry_run`/`live`).
  - Repository structure documented in `README.md`.

### P1-02 Docker packaging and compose service
- Status: `DONE`
- Scope:
  - Add `Dockerfile` and `.dockerignore`.
  - Add `docker-compose.yml` service with persistent volume for SQLite and restart policy.
  - Support local `.env` configuration injection and configurable host port mapping.
- Deliverable:
  - `docker compose up -d` starts container successfully.
  - Container restarts automatically (`unless-stopped`).

### P1-03 Tasmota actuator (MQTT first)
- Status: `DONE`
- Scope:
  - Build command publisher abstraction for `POWER ON` / `POWER OFF`.
  - Implement MQTT publish path using configured Tasmota topic mapping.
  - Add optional HTTP fallback command sender.
- Deliverable:
  - Unit-tested actuator module with dry-run mode logging target topic/payload.

### P1-04 Scheduler with daily evaluation and reset
- Status: `DONE`
- Scope:
  - Schedule `AUTO_OFF_TIME` daily evaluation.
  - Schedule daily override reset at local midnight.
  - Ensure timezone correctness using `TZ` config.
- Deliverable:
  - Scheduler emits expected events in logs for both jobs.

### P1-05 Override persistence and API endpoints
- Status: `DONE`
- Scope:
  - Add SQLite schema for one-time daily override.
  - Implement `POST /override/today` and `DELETE /override/today`.
  - Implement `GET /status` with current override and next evaluation time.
- Deliverable:
  - Override survives service restart and resets next day.

### P1-06 Structured event logging and baseline events table
- Status: `DONE`
- Scope:
  - Define event types and event logger helper.
  - Persist decision events to SQLite (`events` table).
  - Include reason strings in every evaluation outcome.
- Deliverable:
  - `events` table contains inspectable decision history with timestamps and reasons.

### P1-07 Dry-run behavior guardrail
- Status: `DONE`
- Scope:
  - Add config flag to prevent any real power command.
  - Ensure code path still records "would have acted" decisions.
- Deliverable:
  - In dry run, no OFF command is published while evaluation outcomes are logged.

## Phase 2 - Activity-aware Shutdown Engine

### P2-01 Telemetry collector and rolling storage
- Status: `DONE`
- Scope:
  - Subscribe to telemetry and parse `ENERGY.Power` samples.
  - Keep rolling in-memory window and optional recent SQLite rows.
- Deliverable:
  - Collector continuously stores timestamped power values from MQTT.

### P2-02 Activity classifier (idle vs active)
- Status: `DONE`
- Scope:
  - Implement threshold-based classification using `IDLE_WATTS_THRESHOLD` and `ACTIVE_WATTS_THRESHOLD`.
  - Handle missing/late telemetry gracefully.
- Deliverable:
  - Deterministic classifier with unit tests for boundary conditions.

### P2-03 Quiet-window decision logic
- Status: `DONE`
- Scope:
  - Require `QUIET_MINUTES_REQUIRED` continuous idle before OFF.
  - Evaluate state at scheduled check times.
- Deliverable:
  - Decision engine returns `OFF_ALLOWED` only after continuous quiet window.

### P2-04 Postpone and re-evaluate flow
- Status: `DONE`
- Scope:
  - If active at decision time, schedule next check after `POSTPONE_MINUTES`.
  - Prevent duplicate postponed jobs.
- Deliverable:
  - Active use after 20:00 postpones decision loop without command spam.

### P2-05 Hard cutoff enforcement at 01:00
- Status: `DONE`
- Scope:
  - Enforce latest cutoff regardless of activity.
  - Persist and log explicit marker when fallback is used.
- Deliverable:
  - Event `HARD_CUTOFF_USED` recorded when shutdown occurs at cutoff.

### P2-06 Decision inspection endpoint
- Status: `DONE`
- Scope:
  - Add endpoint showing last decision input context (samples, thresholds, reason).
- Deliverable:
  - Operator can inspect why OFF happened or was skipped via API.

## Phase 2a - Dry-run Scripts (MQTT + Threshold Discovery)

### P2A-01 MQTT connectivity and topic probe script
- Status: `DONE`
- Scope:
  - Implement `scripts/mqtt_probe.py`.
  - Connect to broker (support anonymous mode by default).
  - Subscribe to `tele/<topic>/#` and `stat/<topic>/#`, print parsed summaries.
  - Exit non-zero if no telemetry within timeout.
- Deliverable:
  - Script confirms broker and topic wiring without changing plug state.

### P2A-02 Decision simulation dry-run controller
- Status: `DONE`
- Scope:
  - Implement `scripts/mqtt_dry_run_controller.py`.
  - Reuse evaluation rules and emit simulated decisions only.
  - Print "would publish" command details without publishing by default.
- Deliverable:
  - End-to-end simulation output for one evening behavior.

### P2A-03 Power recorder script
- Status: `DONE`
- Scope:
  - Implement `scripts/record_power.py` writing CSV (`timestamp,power_watts`).
  - Add CLI args for duration, output file, and topic.
- Deliverable:
  - CSV data capture for at least one idle and one active session.

### P2A-04 Threshold analysis script
- Status: `DONE`
- Scope:
  - Implement `scripts/analyze_thresholds.py`.
  - Compute quantiles and threshold proposals from recorded CSV.
  - Render markdown report in `artifacts/threshold_report.md`.
- Deliverable:
  - Report with recommended `idle`, `active`, and confidence notes.

### P2A-05 Scripts documentation
- Status: `DONE`
- Scope:
  - Add `scripts/README.md` with examples and expected outputs.
  - Document anonymous vs authenticated MQTT usage.
- Deliverable:
  - One-page operator guide for running all scripts in sequence.

## Phase 3 - Hardening and Operational Quality

### P3-01 Startup reconciliation
- Status: `DONE`
- Scope:
  - Recover pending state/jobs after restart.
  - Rebuild scheduler state from DB and current time.
- Deliverable:
  - Service restart does not lose override and schedule semantics.

### P3-02 Pre-shutdown notification hook
- Status: `DONE`
- Scope:
  - Add optional webhook notification before planned OFF.
  - Include reason, cutoff info, and delay.
- Deliverable:
  - Optional notification appears before automated shutdown.

### P3-03 Metrics exposure
- Status: `DONE`
- Scope:
  - Expose counters/gauges for evaluations, postpones, and offs.
  - Add `/metrics` endpoint (Prometheus format).
- Deliverable:
  - Metrics scraped by Prometheus in homelab.

### P3-04 Integration tests with mocked MQTT/Tasmota I/O
- Status: `DONE`
- Scope:
  - Build integration tests for override, postpone, cutoff, and dry-run safety.
  - Mock telemetry input and command output.
- Deliverable:
  - CI/local test run validates no regression in decision flow.

### P3-05 Ops dashboard starter
- Status: `DONE`
- Scope:
  - Provide optional Grafana dashboard JSON (events and power trend).
- Deliverable:
  - Importable dashboard for quick observability.

## Cross-Phase Tracking

### Current milestone
- Status: `DONE`
- Deliverable:
  - Phase 3 hardening is implemented with reconciliation, notifications, metrics, tests, and a Grafana dashboard starter.

### Implementation rule for commits
- Status: `IN_PROGRESS`
- Scope:
  - Commit automatically at logical checkpoints (scripts, core service, deployment, tests).
- Deliverable:
  - Small, traceable commits with clear messages during implementation.
