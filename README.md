# Desk Power Guardian

Small FastAPI-based microservice to control a Tasmota plug with safe auto-off behavior and one-time override support.

## MVP Features
- Daily auto-off evaluation at `AUTO_OFF_TIME`
- One-time override for today (`POST /override/today`)
- Daily override reset
- Dry-run safety mode (no real `POWER OFF` publish)
- Event history persisted in SQLite

## Quick Start
1. Copy env file and adjust values:
```bash
cp .env.example .env
```
2. Install dependencies:
```bash
pip install -r requirements.txt
```
3. Run locally:
```bash
uvicorn desk_power_guardian.main:app --app-dir src --host 0.0.0.0 --port 8080
```
4. Health check:
```bash
curl http://localhost:8080/health
```

## Docker
Set `SERVICE_PORT` in `.env` to choose the host port that forwards to the container's internal port `8080`.

```bash
docker compose up -d --build
```

Example health check with `SERVICE_PORT=1884`:

```bash
curl http://localhost:1884/health
```

## Important MQTT Config
For your plug, the relevant command path is expected to look like:
- `cmnd/<TASMOTA_BASE_TOPIC>/POWER`

Example:
- `cmnd/tasmota_1C8D21/POWER`

The telemetry collector subscribes to:
- `tele/<TASMOTA_BASE_TOPIC>/SENSOR`

You can tune retention with:
- `TELEMETRY_WINDOW_SIZE` for the in-memory rolling window
- `TELEMETRY_DB_RETENTION` for recent SQLite-backed samples (`0` disables DB retention)

The activity classifier uses:
- `ACTIVE_WATTS_THRESHOLD` to mark usage as active
- `IDLE_WATTS_THRESHOLD` to mark usage as idle
- `QUIET_MINUTES_REQUIRED` to require a continuous idle window before auto-off
- `POSTPONE_MINUTES` to schedule the next re-check when shutdown is blocked
- `TELEMETRY_STALE_SECONDS` to treat delayed telemetry as unusable

## API
- `GET /health`
- `GET /status`
- `GET /decision`
- `GET /metrics`
- `POST /override/today`
- `DELETE /override/today`
- `POST /power/on`
- `POST /power/off-now`
- `POST /evaluate-now`

`GET /status` now includes recent power telemetry samples when available.
It also reports the current activity assessment as `ACTIVE`, `IDLE`, `UNCERTAIN`, `NO_DATA`, or `STALE`.
It reports whether the quiet window is already satisfied for an automatic shutdown decision.
When shutdown is postponed, the status payload includes `next_postponed_evaluation`.
The status payload also includes `next_hard_cutoff` for the mandatory fallback shutdown.

`GET /decision` returns the current thresholds, schedule, recent samples, activity state, quiet-window state, and the latest persisted decision event so you can see why shutdown was allowed or skipped.

`GET /metrics` exposes Prometheus-style counters for evaluations, postpones, and automated shutdowns, plus gauges for override and postponed state.

Postponed re-checks are now persisted in SQLite and restored on startup, so a container restart does not silently drop a pending evening evaluation.

Optional pre-shutdown notifications are available through `NOTIFICATION_WEBHOOK_URL`. When configured, automated `OFF` paths send a JSON webhook before actuation with the reason, cutoff context, command topic, and the configured `PRE_SHUTDOWN_NOTIFY_DELAY_SECONDS`.
