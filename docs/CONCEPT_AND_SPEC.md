# Tasmota Desk SmartPowerSaver

## 1) Problem Summary
The `office` smart plug currently powers off at 20:00 by a fixed timer.
This saves energy, but can interrupt active use (gaming/work) and cause abrupt shutdowns.

Desired behavior:
- Keep saving energy automatically.
- Avoid power-off while the desk is actively in use.
- Allow a one-click/manual "extend tonight" override.
- Run lightweight on a Linux homelab via Docker.

## 2) Constraints and Assumptions
- Tasmota plug exposes power telemetry (W) and can be controlled via MQTT and/or HTTP.
- Homelab has Docker and can run one small always-on container.
- The desk load has a measurable difference between idle and active use.
- Timezone for automation is local timezone of your homelab.

Assumptions to validate:
- The plug is already sending periodic telemetry (`ENERGY.Power`) every ~30-300s.
- You can provide either MQTT broker access or plug HTTP credentials.
- Hard safety cutoff after midnight is acceptable (to prevent running all night by accident).

## 3) Suitable Approaches

### Approach A: Keep Tasmota timer, service only toggles timer on/off
How it works:
- At "extend tonight", service disables timers (or specific timer) in Tasmota.
- Next morning, service re-enables timer.

Pros:
- Minimal moving logic.
- Reuses your existing timer setup.

Cons:
- Harder to reason about edge cases (service restarts, timer state drift).
- Activity-based behavior is awkward because Tasmota timers are static.

### Approach B (Chosen): Service owns shutdown logic, Tasmota timer disabled
How it works:
- Disable plug's internal 20:00 timer permanently.
- Service evaluates activity + schedule and decides when to cut power.
- Service sends `POWER OFF` only when conditions are met.

Pros:
- Single source of truth.
- Easiest to add manual override + activity detection + grace windows.
- Better observability (logs/metrics/events).

Cons:
- Requires reliable service uptime (mitigated by Docker restart policy).

### Approach C: Home Assistant automation (if already used)
How it works:
- Build automations in HA with energy sensor + helper booleans.

Pros:
- Fastest if HA already runs in your homelab.

Cons:
- Less portable and less custom than a standalone microservice.

## 4) Chosen Concept (Hybrid of B + manual override)
Service name: `desk-power-guardian`

Core behavior:
1. Every day at `20:00`, evaluate whether shutdown is allowed.
2. If a one-time override exists for today, skip shutdown.
3. Else, check recent activity from plug power telemetry:
   - If active, postpone (e.g., 30 min), then re-check.
   - If inactive for a minimum quiet window, power off.
4. Hard cutoff at `01:00` (required) to avoid accidental all-night power.
5. At next day boundary, clear one-time override automatically.
6. If hard cutoff is used, write an explicit event/log marker so it is visible in history.

Manual controls:
- `POST /override/today` -> "do not auto-off tonight"
- `DELETE /override/today` -> cancel override
- `POST /power/off-now` -> immediate off
- `POST /power/on` -> immediate on

## 5) Activity Detection Specification
Use a robust low-cost heuristic first, then tune:

Inputs:
- `power_watts` from Tasmota telemetry.
- Timestamp per sample.

Configurable thresholds:
- `active_watts_threshold` (example start: 45W)
- `idle_watts_threshold` (example start: 20W)
- `quiet_minutes_required` (example: 20)
- `postpone_minutes` (example: 30)
- `hard_cutoff_time` (example: 01:00)

Decision rule (MVP):
- Mark sample as active if `power_watts >= active_watts_threshold`.
- Mark idle if `power_watts <= idle_watts_threshold`.
- At/after 20:00, only power off if idle has been continuous for `quiet_minutes_required`.
- If not idle long enough, postpone next check.

Why this works:
- Gaming/working typically causes repeated spikes and sustained > idle draw.
- Quiet window prevents immediate off during short low-power moments.

## 6) Service Architecture
- `collector`: subscribes to telemetry (MQTT preferred) or polls HTTP fallback.
- `activity-engine`: keeps rolling window and computes active/idle state.
- `scheduler`: triggers evaluation events (20:00, postponed checks, midnight reset).
- `actuator`: sends Tasmota commands (`POWER ON/OFF`, optional timer commands).
- `api`: manual override and status endpoints.
- `store`: SQLite for durable state (override + recent decisions + config snapshot).

Recommended stack (minimal impact):
- Python 3.12
- FastAPI + Uvicorn
- APScheduler (or simple async scheduler)
- paho-mqtt
- SQLite (built-in `sqlite3`)
- Docker single container

## 7) External Interfaces

### Tasmota control/telemetry
Preferred: MQTT
- Subscribe telemetry topic, parse `ENERGY.Power`.
- Publish power commands to cmnd topic.

Fallback: HTTP
- Poll status endpoint every N seconds.
- Send HTTP command for on/off.

### REST API (service)
- `GET /health`
- `GET /status`
- `POST /override/today`
- `DELETE /override/today`
- `POST /power/on`
- `POST /power/off-now`
- `POST /evaluate-now` (manual run for testing)

## 8) Data Model (SQLite)
Table: `override`
- `id` (pk)
- `date_local` (YYYY-MM-DD)
- `enabled` (bool)
- `created_at`
- `expires_at`

Table: `telemetry_recent`
- `timestamp`
- `power_watts`

Table: `events`
- `timestamp`
- `type` (EVALUATION, OFF_TRIGGERED, POSTPONED, OVERRIDE_SET, etc.)
- `details_json`

## 9) Configuration (env vars)
- `TZ=Europe/Berlin`
- `OFFICE_PLUG_NAME=office`
- `AUTO_OFF_TIME=20:00`
- `HARD_CUTOFF_TIME=01:00`
- `ACTIVE_WATTS_THRESHOLD=45`
- `IDLE_WATTS_THRESHOLD=20`
- `QUIET_MINUTES_REQUIRED=20`
- `POSTPONE_MINUTES=30`
- `MQTT_HOST`
- `MQTT_PORT`
- `MQTT_USERNAME`
- `MQTT_PASSWORD`
- `TASMOTA_TOPIC`
- `HTTP_FALLBACK_URL` (optional)

## 10) Implementation Tasks

### Phase 1: MVP manual override + scheduled off
1. Scaffold service, Dockerfile, and docker-compose service.
2. Implement Tasmota actuator (MQTT first, HTTP fallback optional).
3. Implement scheduler for 20:00 evaluate + midnight override reset.
4. Implement one-time override endpoints and persistence.
5. Add basic status endpoint and structured logs.
6. Test with dry-run mode (log action without switching power).

### Phase 2: Activity-aware shutdown
1. Implement telemetry collector and rolling window.
2. Add active/idle classifier + quiet-window logic.
3. Add postpone/re-evaluate flow.
4. Add hard cutoff enforcement.
5. Add endpoint to inspect last decision context.
6. Add explicit event type `HARD_CUTOFF_USED` when 01:00 fallback powers off.

### Phase 2a: Dry-run scripts for MQTT validation and data capture
1. Add `scripts/mqtt_probe.py`:
   - Connect to Mosquitto with env credentials.
   - Subscribe to `stat/<topic>/#` and `tele/<topic>/#`.
   - Print parsed summaries for `SENSOR`, `STATE`, and `POWER` messages.
   - Exit non-zero if no telemetry arrives within configurable timeout.
2. Add `scripts/mqtt_dry_run_controller.py`:
   - Simulate shutdown evaluation loop without sending `POWER OFF`.
   - Log decision outcome (`OFF_ALLOWED`, `POSTPONED_ACTIVE`, `OVERRIDE_ACTIVE`, `HARD_CUTOFF_USED`).
   - Optionally emit "would publish to" command topic for operator verification.
3. Add `scripts/record_power.py`:
   - Consume power telemetry and append CSV rows (`timestamp,power_watts`).
   - Support run duration and output path flags.
4. Add `scripts/analyze_thresholds.py`:
   - Read recorded CSV.
   - Compute quantiles, histogram, and suggested `idle`/`active` thresholds.
   - Produce markdown report `artifacts/threshold_report.md`.
5. Add `scripts/README.md` with usage examples and expected outcomes.

### Phase 3: Hardening and usability
1. Add startup reconciliation (recover state after restart).
2. Add notification hook (Discord/Telegram/ntfy) before off.
3. Add metrics (Prometheus optional).
4. Add integration tests with mocked Tasmota I/O.
5. Add sample Grafana dashboard (optional).

## 11) Acceptance Criteria
- At 20:00, desk does not switch off if active use is detected.
- "Extend tonight" prevents auto-off only for the current evening.
- Override resets automatically next day.
- Service survives container restart without forgetting override state.
- Manual API `off-now` still works immediately.
- Logs clearly explain every auto-off decision.

## 12) Deployment Notes
- Use `restart: unless-stopped` in Docker Compose.
- Mount persistent volume for SQLite database.
- Keep container on same network as MQTT broker/Tasmota device.
- Start in dry-run mode for 2-3 evenings to tune thresholds before enabling real power-off.

## 13) Confirmed Inputs (From Your Answers)
1. MQTT broker exists (Mosquitto in Docker) and will be used as primary integration.
2. Hard latest cutoff is required at `01:00`, with explicit indication when this fallback is used.
3. Power ranges are not yet known; they will be determined from recorded telemetry.
4. Manual trigger path will be HTTP requests (bookmark/home landing page integration).
5. Scope is single plug (`office`) for v1.
