from __future__ import annotations

import unittest
from dataclasses import dataclass
from datetime import datetime, timedelta

from desk_power_guardian.actuator import ActuationResult
from desk_power_guardian.config import Settings
from desk_power_guardian.db import Database
from desk_power_guardian.notifier import NotificationResult
from desk_power_guardian.service import POSTPONED_EVALUATION_JOB_ID, GuardianService


@dataclass(frozen=True)
class Sample:
    created_at: datetime
    topic: str
    power_watts: float


class FakeTelemetry:
    def __init__(self, samples: list[Sample] | None = None) -> None:
        self.samples = samples or []

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def status(self) -> dict:
        return {"sample_count": len(self.samples)}

    def latest_sample(self):
        return self.samples[-1] if self.samples else None

    def recent_samples(self, limit: int = 10):
        if limit <= 0:
            return []
        return self.samples[-limit:]


class FakeActuator:
    def __init__(self, result: ActuationResult) -> None:
        self.result = result
        self.calls: list[tuple[str, str]] = []

    def send_power(self, power_state: str, reason: str) -> ActuationResult:
        self.calls.append((power_state, reason))
        return self.result


class FakeNotifier:
    def __init__(self) -> None:
        self.calls: list[tuple[str, datetime | None]] = []

    def notify_pre_shutdown(self, now: datetime, reason: str, hard_cutoff_at: datetime | None, dry_run: bool) -> NotificationResult:
        self.calls.append((reason, hard_cutoff_at))
        return NotificationResult(
            attempted=False,
            success=False,
            detail="notification webhook not configured",
            delay_seconds=0,
            planned_shutdown_at=now.isoformat(),
        )


class TestGuardianService(GuardianService):
    def __init__(self, settings: Settings, db: Database, now: datetime) -> None:
        self._fixed_now = now
        super().__init__(settings=settings, db=db)

    def _now(self) -> datetime:
        return self._fixed_now


def build_settings() -> Settings:
    return Settings(
        tz="Europe/Berlin",
        dry_run=True,
        auto_off_time=datetime(2026, 4, 14, 20, 0, 0).time(),
        reset_time=datetime(2026, 4, 15, 0, 5, 0).time(),
        hard_cutoff_time=datetime(2026, 4, 15, 1, 0, 0).time(),
        active_watts_threshold=45.0,
        idle_watts_threshold=20.0,
        quiet_minutes_required=20,
        postpone_minutes=30,
        telemetry_stale_seconds=900,
        mqtt_host="127.0.0.1",
        mqtt_port=1883,
        mqtt_allow_anonymous=True,
        mqtt_username=None,
        mqtt_password=None,
        tasmota_base_topic="tasmota_1C8D21",
        tasmota_command_prefix="cmnd",
        tasmota_status_prefix="stat",
        telemetry_topic_prefix="tele",
        telemetry_sensor_suffix="SENSOR",
        telemetry_window_size=120,
        telemetry_db_retention=500,
        http_fallback_url=None,
        notification_webhook_url=None,
        notification_timeout_seconds=5,
        pre_shutdown_notify_delay_seconds=0,
        sqlite_path=":memory:",
    )


class ServiceIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime.fromisoformat("2026-04-14T20:30:00+02:00")
        self.settings = build_settings()
        self.db = Database(":memory:")
        self.db.init_schema()
        self.service = TestGuardianService(self.settings, self.db, now=self.now)
        self.service._register_jobs()
        self.service.notifier = FakeNotifier()

    def tearDown(self) -> None:
        self.db.close()

    def test_override_active_skips_actuation(self) -> None:
        self.db.set_override(self.now.date().isoformat(), self.now.isoformat())
        self.service.telemetry = FakeTelemetry([])
        actuator = FakeActuator(ActuationResult(True, "dry_run", "would publish OFF"))
        self.service.actuator = actuator

        result = self.service.evaluate_and_maybe_turn_off()

        self.assertEqual(result.action, "SKIP")
        self.assertEqual(result.reason, "OVERRIDE_ACTIVE")
        self.assertEqual(actuator.calls, [])

    def test_blocked_evaluation_schedules_postponed_job(self) -> None:
        self.service.telemetry = FakeTelemetry([])
        actuator = FakeActuator(ActuationResult(True, "dry_run", "would publish OFF"))
        self.service.actuator = actuator

        result = self.service.evaluate_and_maybe_turn_off()

        self.assertEqual(result.action, "SKIP")
        self.assertEqual(result.details["schedule_action"], "scheduled")
        self.assertIsNotNone(self.service.scheduler.get_job(POSTPONED_EVALUATION_JOB_ID))
        self.assertEqual(actuator.calls, [])

    def test_hard_cutoff_uses_actuator_and_logs_event(self) -> None:
        self.service.telemetry = FakeTelemetry([])
        actuator = FakeActuator(ActuationResult(True, "dry_run", "would publish OFF"))
        self.service.actuator = actuator

        result = self.service.enforce_hard_cutoff()

        self.assertEqual(result.action, "OFF")
        self.assertEqual(actuator.calls, [("OFF", "HARD_CUTOFF")])
        self.assertEqual(self.db.list_recent_events(limit=1)[0].event_type, "HARD_CUTOFF_USED")

    def test_dry_run_auto_off_reports_would_publish(self) -> None:
        self.service.telemetry = FakeTelemetry(
            [
                Sample(self.now - timedelta(minutes=25), "tele/tasmota_1C8D21/SENSOR", 10.0),
                Sample(self.now - timedelta(minutes=10), "tele/tasmota_1C8D21/SENSOR", 12.0),
                Sample(self.now - timedelta(minutes=1), "tele/tasmota_1C8D21/SENSOR", 11.0),
            ]
        )

        result = self.service.evaluate_and_maybe_turn_off()

        self.assertEqual(result.action, "OFF")
        self.assertEqual(result.details["mode"], "dry_run")
        self.assertIn("would publish OFF", result.details["detail"])


if __name__ == "__main__":
    unittest.main()