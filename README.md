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

## API
- `GET /health`
- `GET /status`
- `POST /override/today`
- `DELETE /override/today`
- `POST /power/on`
- `POST /power/off-now`
- `POST /evaluate-now`
