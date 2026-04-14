from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.cron import CronTrigger

from .actuator import TasmotaActuator
from .activity import ActivityClassifier
from .config import Settings
from .db import Database
from .notifier import ShutdownNotifier
from .telemetry import TelemetryCollector

LOGGER = logging.getLogger(__name__)
POSTPONED_EVALUATION_JOB_ID = "postponed_auto_off_evaluation"
HARD_CUTOFF_JOB_ID = "daily_hard_cutoff"
POSTPONED_EVALUATION_STATE_KEY = "postponed_evaluation"
RECONCILIATION_GRACE_SECONDS = 5


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
        self.notifier = ShutdownNotifier(settings)
        self.telemetry = TelemetryCollector(settings=settings, db=db, now_provider=self._now)
        self.scheduler = AsyncIOScheduler(timezone=settings.timezone)

    def start(self) -> None:
        self.db.init_schema()
        self._register_jobs()
        self._reconcile_startup_state()
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
        hard_cutoff = self.settings.hard_cutoff_time

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
        self.scheduler.add_job(
            self.enforce_hard_cutoff,
            trigger=CronTrigger(hour=hard_cutoff.hour, minute=hard_cutoff.minute),
            id=HARD_CUTOFF_JOB_ID,
            replace_existing=True,
        )

    def _get_job_next_run_time(self, job_id: str) -> str | None:
        job = self.scheduler.get_job(job_id) if self.scheduler.running else None
        if job is None or job.next_run_time is None:
            return None
        return job.next_run_time.isoformat()

    def _clear_postponed_evaluation(self) -> None:
        if self.scheduler.get_job(POSTPONED_EVALUATION_JOB_ID) is not None:
            self.scheduler.remove_job(POSTPONED_EVALUATION_JOB_ID)
        self.db.clear_service_state(POSTPONED_EVALUATION_STATE_KEY)

    def _persist_postponed_evaluation(
        self,
        run_at: datetime,
        hard_cutoff_at: datetime,
        reason: str,
        quiet_window: dict,
    ) -> None:
        self.db.set_service_state(
            POSTPONED_EVALUATION_STATE_KEY,
            {
                "scheduled_for": run_at.isoformat(),
                "hard_cutoff_at": hard_cutoff_at.isoformat(),
                "reason": reason,
                "quiet_window": quiet_window,
            },
            updated_at_iso=self._now().isoformat(),
        )

    def _reconcile_startup_state(self) -> None:
        pending = self.db.get_service_state(POSTPONED_EVALUATION_STATE_KEY)
        if pending is None:
            return

        scheduled_for = datetime.fromisoformat(pending["scheduled_for"])
        hard_cutoff_at = datetime.fromisoformat(pending["hard_cutoff_at"])
        now = self._now()

        if now >= hard_cutoff_at:
            self.db.clear_service_state(POSTPONED_EVALUATION_STATE_KEY)
            self.log_event(
                "STARTUP_RECONCILIATION_CLEARED",
                {
                    "reason": "POSTPONED_EVALUATION_EXPIRED",
                    "scheduled_for": scheduled_for.isoformat(),
                    "hard_cutoff_at": hard_cutoff_at.isoformat(),
                },
            )
            return

        run_at = scheduled_for
        schedule_action = "restored"
        if scheduled_for <= now:
            run_at = min(now + timedelta(seconds=RECONCILIATION_GRACE_SECONDS), hard_cutoff_at)
            schedule_action = "rescheduled_immediate"

        self.scheduler.add_job(
            self.evaluate_and_maybe_turn_off,
            trigger=DateTrigger(run_date=run_at),
            id=POSTPONED_EVALUATION_JOB_ID,
            replace_existing=True,
        )
        self._persist_postponed_evaluation(
            run_at=run_at,
            hard_cutoff_at=hard_cutoff_at,
            reason=pending.get("reason", "RECONCILED"),
            quiet_window=pending.get("quiet_window", {}),
        )
        self.log_event(
            "STARTUP_RECONCILIATION_RESTORED",
            {
                "schedule_action": schedule_action,
                "scheduled_for": run_at.isoformat(),
                "original_scheduled_for": scheduled_for.isoformat(),
                "hard_cutoff_at": hard_cutoff_at.isoformat(),
            },
        )

    def _next_hard_cutoff_datetime(self, now: datetime) -> datetime:
        auto_off_today = now.replace(
            hour=self.settings.auto_off_time.hour,
            minute=self.settings.auto_off_time.minute,
            second=0,
            microsecond=0,
        )
        cutoff = now.replace(
            hour=self.settings.hard_cutoff_time.hour,
            minute=self.settings.hard_cutoff_time.minute,
            second=0,
            microsecond=0,
        )
        reference_time = auto_off_today if now < auto_off_today else now
        while cutoff <= reference_time:
            cutoff += timedelta(days=1)
        return cutoff

    def _schedule_postponed_evaluation(self, now: datetime, reason: str, quiet_window: dict) -> tuple[str, str]:
        run_at = now + timedelta(minutes=self.settings.postpone_minutes)
        hard_cutoff_at = self._next_hard_cutoff_datetime(now)

        existing_job = self.scheduler.get_job(POSTPONED_EVALUATION_JOB_ID)
        if existing_job is not None and existing_job.next_run_time is not None:
            existing_run = existing_job.next_run_time
            if existing_run <= run_at:
                self.log_event(
                    "POSTPONED_EVALUATION_REUSED",
                    {
                        "reason": reason,
                        "scheduled_for": existing_run.isoformat(),
                        "postpone_minutes": self.settings.postpone_minutes,
                        "quiet_window": quiet_window,
                    },
                )
                return existing_run.isoformat(), "reused"

        if run_at >= hard_cutoff_at:
            self._clear_postponed_evaluation()
            self.log_event(
                "POSTPONED_EVALUATION_SKIPPED",
                {
                    "reason": reason,
                    "scheduled_for": hard_cutoff_at.isoformat(),
                    "postpone_minutes": self.settings.postpone_minutes,
                    "schedule_action": "hard_cutoff_pending",
                    "quiet_window": quiet_window,
                },
            )
            return hard_cutoff_at.isoformat(), "hard_cutoff_pending"

        self.scheduler.add_job(
            self.evaluate_and_maybe_turn_off,
            trigger=DateTrigger(run_date=run_at),
            id=POSTPONED_EVALUATION_JOB_ID,
            replace_existing=True,
        )
        self._persist_postponed_evaluation(
            run_at=run_at,
            hard_cutoff_at=hard_cutoff_at,
            reason=reason,
            quiet_window=quiet_window,
        )
        self.log_event(
            "POSTPONED_EVALUATION_SCHEDULED",
            {
                "reason": reason,
                "scheduled_for": run_at.isoformat(),
                "postpone_minutes": self.settings.postpone_minutes,
                "quiet_window": quiet_window,
            },
        )
        return run_at.isoformat(), "scheduled"

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

    def enforce_hard_cutoff(self) -> EvaluationResult:
        self._clear_postponed_evaluation()
        now = self._now()
        notification = self.notifier.notify_pre_shutdown(
            now=now,
            reason="HARD_CUTOFF",
            hard_cutoff_at=now,
            dry_run=self.settings.dry_run,
        )
        actuation = self.actuator.send_power("OFF", reason="HARD_CUTOFF")
        details = {
            "mode": actuation.mode,
            "detail": actuation.detail,
            "dry_run": self.settings.dry_run,
            "notification": {
                "attempted": notification.attempted,
                "success": notification.success,
                "detail": notification.detail,
                "delay_seconds": notification.delay_seconds,
                "planned_shutdown_at": notification.planned_shutdown_at,
            },
        }

        if actuation.success:
            self.log_event("HARD_CUTOFF_USED", details)
            return EvaluationResult(action="OFF", reason="HARD_CUTOFF", details=details)

        self.log_event("HARD_CUTOFF_FAILED", details)
        return EvaluationResult(action="ERROR", reason="HARD_CUTOFF", details=details)

    def evaluate_and_maybe_turn_off(self) -> EvaluationResult:
        now = self._now()
        date_local = now.date().isoformat()
        quiet_window = self.activity.assess_quiet_window(
            self.telemetry.recent_samples(limit=self.settings.telemetry_window_size),
            now=now,
        )

        self.log_event(
            "EVALUATION",
            {
                "date_local": date_local,
                "time": now.time().isoformat(),
                "quiet_window": {
                    "off_allowed": quiet_window.off_allowed,
                    "reason": quiet_window.reason,
                    "quiet_for_seconds": quiet_window.quiet_for_seconds,
                    "quiet_minutes_required": quiet_window.quiet_minutes_required,
                    "latest_state": quiet_window.latest_state,
                    "latest_power_watts": quiet_window.latest_power_watts,
                    "latest_sample_time": quiet_window.latest_sample_time,
                    "idle_since": quiet_window.idle_since,
                    "considered_samples": quiet_window.considered_samples,
                },
            },
        )

        if self.db.has_override(date_local):
            self._clear_postponed_evaluation()
            result = EvaluationResult(
                action="SKIP",
                reason="OVERRIDE_ACTIVE",
                details={"date_local": date_local},
            )
            self.log_event("OVERRIDE_ACTIVE", result.details)
            return result

        if not quiet_window.off_allowed:
            quiet_window_details = {
                "reason": quiet_window.reason,
                "quiet_for_seconds": quiet_window.quiet_for_seconds,
                "quiet_minutes_required": quiet_window.quiet_minutes_required,
                "latest_state": quiet_window.latest_state,
                "latest_power_watts": quiet_window.latest_power_watts,
                "latest_sample_time": quiet_window.latest_sample_time,
                "idle_since": quiet_window.idle_since,
                "considered_samples": quiet_window.considered_samples,
            }
            postponed_for, schedule_action = self._schedule_postponed_evaluation(
                now=now,
                reason=quiet_window.reason,
                quiet_window=quiet_window_details,
            )
            details = {
                "date_local": date_local,
                "quiet_window": quiet_window_details,
                "postponed_for": postponed_for,
                "schedule_action": schedule_action,
            }
            self.log_event("OFF_SKIPPED", details)
            return EvaluationResult(
                action="SKIP",
                reason=quiet_window.reason,
                details=details,
            )

        self._clear_postponed_evaluation()
        notification = self.notifier.notify_pre_shutdown(
            now=now,
            reason="SCHEDULED_AUTO_OFF",
            hard_cutoff_at=self._next_hard_cutoff_datetime(now),
            dry_run=self.settings.dry_run,
        )
        actuation = self.actuator.send_power("OFF", reason="SCHEDULED_AUTO_OFF")
        event_type = "OFF_TRIGGERED" if actuation.success else "OFF_FAILED"
        details = {
            "mode": actuation.mode,
            "detail": actuation.detail,
            "dry_run": self.settings.dry_run,
            "notification": {
                "attempted": notification.attempted,
                "success": notification.success,
                "detail": notification.detail,
                "delay_seconds": notification.delay_seconds,
                "planned_shutdown_at": notification.planned_shutdown_at,
            },
            "quiet_window": {
                "reason": quiet_window.reason,
                "quiet_for_seconds": quiet_window.quiet_for_seconds,
                "quiet_minutes_required": quiet_window.quiet_minutes_required,
                "latest_state": quiet_window.latest_state,
                "latest_power_watts": quiet_window.latest_power_watts,
                "latest_sample_time": quiet_window.latest_sample_time,
                "idle_since": quiet_window.idle_since,
                "considered_samples": quiet_window.considered_samples,
            },
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

    def decision_context(self) -> dict:
        jobs = self.scheduler.get_jobs() if self.scheduler.running else []
        next_auto_off = None
        next_hard_cutoff = None
        next_postponed_evaluation = None
        for job in jobs:
            if job.id == "daily_auto_off_evaluation" and job.next_run_time is not None:
                next_auto_off = job.next_run_time.isoformat()
            if job.id == HARD_CUTOFF_JOB_ID and job.next_run_time is not None:
                next_hard_cutoff = job.next_run_time.isoformat()
            if job.id == POSTPONED_EVALUATION_JOB_ID and job.next_run_time is not None:
                next_postponed_evaluation = job.next_run_time.isoformat()

        now = self._now()
        telemetry_window = self.telemetry.recent_samples(limit=self.settings.telemetry_window_size)
        display_samples = telemetry_window[-10:]
        activity = self.activity.assess_latest(self.telemetry.latest_sample(), now=now)
        quiet_window = self.activity.assess_quiet_window(telemetry_window, now=now)
        recent_events = self.db.list_recent_events(limit=20)

        last_decision_event = None
        for event in recent_events:
            if event.event_type in {
                "OFF_TRIGGERED",
                "OFF_FAILED",
                "OFF_SKIPPED",
                "OVERRIDE_ACTIVE",
                "HARD_CUTOFF_USED",
                "HARD_CUTOFF_FAILED",
            }:
                last_decision_event = {
                    "event_type": event.event_type,
                    "created_at": event.created_at.isoformat(),
                    "details": event.details,
                }
                break

        return {
            "evaluated_at": now.isoformat(),
            "today": now.date().isoformat(),
            "override_today": self.db.has_override(now.date().isoformat()),
            "thresholds": {
                "active_watts_threshold": self.settings.active_watts_threshold,
                "idle_watts_threshold": self.settings.idle_watts_threshold,
                "quiet_minutes_required": self.settings.quiet_minutes_required,
                "postpone_minutes": self.settings.postpone_minutes,
                "telemetry_stale_seconds": self.settings.telemetry_stale_seconds,
            },
            "schedule": {
                "auto_off_time": self.settings.auto_off_time.isoformat(),
                "hard_cutoff_time": self.settings.hard_cutoff_time.isoformat(),
                "next_auto_off": next_auto_off,
                "next_hard_cutoff": next_hard_cutoff,
                "next_postponed_evaluation": next_postponed_evaluation,
            },
            "activity": {
                "state": activity.state,
                "reason": activity.reason,
                "power_watts": activity.power_watts,
                "sample_age_seconds": activity.sample_age_seconds,
                "sample_time": activity.sample_time,
            },
            "quiet_window": {
                "off_allowed": quiet_window.off_allowed,
                "reason": quiet_window.reason,
                "quiet_for_seconds": quiet_window.quiet_for_seconds,
                "quiet_minutes_required": quiet_window.quiet_minutes_required,
                "latest_state": quiet_window.latest_state,
                "latest_power_watts": quiet_window.latest_power_watts,
                "latest_sample_time": quiet_window.latest_sample_time,
                "idle_since": quiet_window.idle_since,
                "considered_samples": quiet_window.considered_samples,
            },
            "recent_samples": [
                {
                    "created_at": sample.created_at.isoformat(),
                    "topic": sample.topic,
                    "power_watts": sample.power_watts,
                }
                for sample in display_samples
            ],
            "last_decision_event": last_decision_event,
        }

    def status(self) -> dict:
        today_key = self._today_key()
        events = self.db.list_recent_events(limit=10)
        decision = self.decision_context()

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
                "activity": decision["activity"],
                "quiet_window": decision["quiet_window"],
                "recent_samples": decision["recent_samples"],
            },
            "today": today_key,
            "override_today": self.db.has_override(today_key),
            "next_auto_off": decision["schedule"]["next_auto_off"],
            "next_hard_cutoff": decision["schedule"]["next_hard_cutoff"],
            "next_postponed_evaluation": decision["schedule"]["next_postponed_evaluation"],
            "recent_events": [
                {
                    "event_type": event.event_type,
                    "created_at": event.created_at.isoformat(),
                    "details": event.details,
                }
                for event in events
            ],
        }

    def metrics_text(self) -> str:
        from .metrics import render_metrics

        return render_metrics(self)
