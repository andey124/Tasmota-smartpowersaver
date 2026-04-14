from __future__ import annotations

import logging

from fastapi import FastAPI

from .config import load_settings
from .db import Database
from .service import GuardianService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

LOGGER = logging.getLogger(__name__)

settings = load_settings()
db = Database(settings.sqlite_path)
service = GuardianService(settings=settings, db=db)

app = FastAPI(title="Desk Power Guardian", version="0.1.0")


@app.on_event("startup")
def startup_event() -> None:
    service.start()
    LOGGER.info("service started")


@app.on_event("shutdown")
def shutdown_event() -> None:
    service.stop()
    db.close()
    LOGGER.info("service stopped")


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "desk-power-guardian",
        "dry_run": settings.dry_run,
    }


@app.get("/status")
def status() -> dict:
    return service.status()


@app.get("/decision")
def decision() -> dict:
    return service.decision_context()


@app.post("/override/today")
def set_override_today() -> dict:
    service.set_override_for_today()
    return {"ok": True, "override_today": True}


@app.delete("/override/today")
def clear_override_today() -> dict:
    removed = service.clear_override_for_today()
    return {"ok": True, "override_today": False, "removed": removed}


@app.post("/power/on")
def power_on() -> dict:
    result = service.turn_power_on_now()
    return {"ok": result.action != "ERROR", "result": result.action, "reason": result.reason, "details": result.details}


@app.post("/power/off-now")
def power_off_now() -> dict:
    result = service.turn_power_off_now()
    return {"ok": result.action != "ERROR", "result": result.action, "reason": result.reason, "details": result.details}


@app.post("/evaluate-now")
def evaluate_now() -> dict:
    result = service.evaluate_and_maybe_turn_off()
    return {"ok": result.action != "ERROR", "result": result.action, "reason": result.reason, "details": result.details}
