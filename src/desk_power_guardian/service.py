from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from .actuator import TasmotaActuator
from .activity import ActivityClassifier
from .config import Settings
from .db import Database
from .telemetry import TelemetryCollector

LOGGER = logging.getLogger(__name__)


@dataclass
class EvaluationResult:
    action: str
    reason: str
    details: dict


class GuardianService:
    def __init__(self, settings: Settings, db: Database) -> None:
        self.settings = settings
        self.db = db
        self.actuator = TasmotaActuator(settings)
        self.activity = ActivityClassifier(settings)
        self.telemetry = TelemetryCollector(settings=settings, db=db, now_provider=self._now)
        self.scheduler = AsyncIOScheduler(timezone=settings.timezone)

    def start(self) -> None:
        self.db.init_schema()
        self._register_jobs()
        self.telemetry.start()
        self.scheduler.start()
        self.log_event("SERVICE_STARTED", {"dry_run": self.settings.dry_run})

    def stop(self) -> None:
        self.telemetry.stop()
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
        self.log_event("SERVICE_STOPPED", {})

    def _register_jobs(self) -> None:
        auto_off = self.settings.auto_off_time
        reset = self.settings.reset_time

        self.scheduler.add_job(
            self.evaluate_and_maybe_turn_off,
            trigger=CronTrigger(hour=auto_off.hour, minute=auto_off.minute),
            id="daily_auto_off_evaluation",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.reset_daily_override,
            trigger=CronTrigger(hour=reset.hour, minute=reset.minute),
            id="daily_override_reset",
            replace_existing=True,
        )

    def _now(self) -> datetime:
        return datetime.now(self.settings.timezone)

    def _today_key(self) -> str:
        return self._now().date().isoformat()

    def log_event(self, event_type: str, details: dict) -> None:
        self.db.log_event(event_type, details, self._now().isoformat())

    def set_override_for_today(self) -> None:
        date_local = self._today_key()
        self.db.set_override(date_local, self._now().isoformat())
        self.log_event("OVERRIDE_SET", {"date_local": date_local})

    def clear_override_for_today(self) -> bool:
        date_local = self._today_key()
        affected = self.db.clear_override(date_local)
        self.log_event("OVERRIDE_CLEARED", {"date_local": date_local, "affected": affected})
        return affected > 0

    def reset_daily_override(self) -> None:
        removed = self.db.clear_all_overrides()
        self.log_event("OVERRIDE_RESET", {"removed_rows": removed})

    def evaluate_and_maybe_turn_off(self) -> EvaluationResult:
        now = self._now()
        date_local = now.date().isoformat()

        self.log_event("EVALUATION", {"date_local": date_local, "time": now.time().isoformat()})

        if self.db.has_override(date_local):
            result = EvaluationResult(
                action="SKIP",
                reason="OVERRIDE_ACTIVE",
                details={"date_local": date_local},
            )
            self.log_event("OVERRIDE_ACTIVE", result.details)
            return result

        actuation = self.actuator.send_power("OFF", reason="SCHEDULED_AUTO_OFF")
        event_type = "OFF_TRIGGERED" if actuation.success else "OFF_FAILED"
        details = {
            "mode": actuation.mode,
            "detail": actuation.detail,
            "dry_run": self.settings.dry_run,
        }
        self.log_event(event_type, details)

        return EvaluationResult(
            action="OFF" if actuation.success else "ERROR",
            reason="SCHEDULED_AUTO_OFF",
            details=details,
        )

    def turn_power_on_now(self) -> EvaluationResult:
        actuation = self.actuator.send_power("ON", reason="MANUAL_POWER_ON")
        self.log_event(
            "POWER_ON_MANUAL",
            {"mode": actuation.mode, "detail": actuation.detail, "dry_run": self.settings.dry_run},
        )
        return EvaluationResult(
            action="ON" if actuation.success else "ERROR",
            reason="MANUAL_POWER_ON",
            details={"mode": actuation.mode, "detail": actuation.detail},
        )

    def turn_power_off_now(self) -> EvaluationResult:
        actuation = self.actuator.send_power("OFF", reason="MANUAL_POWER_OFF")
        self.log_event(
            "POWER_OFF_MANUAL",
            {"mode": actuation.mode, "detail": actuation.detail, "dry_run": self.settings.dry_run},
        )
        return EvaluationResult(
            action="OFF" if actuation.success else "ERROR",
            reason="MANUAL_POWER_OFF",
            details={"mode": actuation.mode, "detail": actuation.detail},
        )

    def status(self) -> dict:
        jobs = self.scheduler.get_jobs() if self.scheduler.running else []
        next_auto_off = None
        for job in jobs:
            if job.id == "daily_auto_off_evaluation" and job.next_run_time is not None:
                next_auto_off = job.next_run_time.isoformat()

        today_key = self._today_key()
        events = self.db.list_recent_events(limit=10)
        activity = self.activity.assess_latest(self.telemetry.latest_sample(), now=self._now())

        return {
            "service": "desk-power-guardian",
            "timezone": self.settings.tz,
            "dry_run": self.settings.dry_run,
            "mqtt": {
                "host": self.settings.mqtt_host,
                "port": self.settings.mqtt_port,
                "allow_anonymous": self.settings.mqtt_allow_anonymous,
                "command_topic": self.settings.command_topic,
                "telemetry_topic": self.settings.telemetry_topic,
            },
            "telemetry": {
                **self.telemetry.status(),
                "activity": {
                    "state": activity.state,
                    "reason": activity.reason,
                    "power_watts": activity.power_watts,
                    "sample_age_seconds": activity.sample_age_seconds,
                    "sample_time": activity.sample_time,
                },
                "recent_samples": [
                    {
                        "created_at": sample.created_at.isoformat(),
                        "topic": sample.topic,
                        "power_watts": sample.power_watts,
                    }
                    for sample in self.telemetry.recent_samples(limit=10)
                ],
            },
            "today": today_key,
            "override_today": self.db.has_override(today_key),
            "next_auto_off": next_auto_off,
            "recent_events": [
                {
                    "event_type": event.event_type,
                    "created_at": event.created_at.isoformat(),
                    "details": event.details,
                }
                for event in events
            ],
        }
