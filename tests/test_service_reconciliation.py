from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from desk_power_guardian.config import Settings
from desk_power_guardian.db import Database
from desk_power_guardian.service import (
    POSTPONED_EVALUATION_JOB_ID,
    POSTPONED_EVALUATION_STATE_KEY,
    RECONCILIATION_GRACE_SECONDS,
    GuardianService,
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


class StartupReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime.fromisoformat("2026-04-14T22:00:00+02:00")
        self.settings = build_settings()
        self.db = Database(":memory:")
        self.db.init_schema()
        self.service = TestGuardianService(settings=self.settings, db=self.db, now=self.now)
        self.service._register_jobs()

    def tearDown(self) -> None:
        self.db.close()

    def test_reconciles_future_postponed_evaluation(self) -> None:
        scheduled_for = datetime.fromisoformat("2026-04-14T22:30:00+02:00")
        hard_cutoff_at = datetime.fromisoformat("2026-04-15T01:00:00+02:00")
        self.db.set_service_state(
            POSTPONED_EVALUATION_STATE_KEY,
            {
                "scheduled_for": scheduled_for.isoformat(),
                "hard_cutoff_at": hard_cutoff_at.isoformat(),
                "reason": "NO_TELEMETRY_RECEIVED",
                "quiet_window": {},
            },
            updated_at_iso=self.now.isoformat(),
        )

        self.service._reconcile_startup_state()

        job = self.service.scheduler.get_job(POSTPONED_EVALUATION_JOB_ID)
        self.assertIsNotNone(job)
        self.assertEqual(job.trigger.run_date.isoformat(), scheduled_for.isoformat())
        state = self.db.get_service_state(POSTPONED_EVALUATION_STATE_KEY)
        self.assertIsNotNone(state)
        self.assertEqual(state["scheduled_for"], scheduled_for.isoformat())

    def test_reconciles_overdue_postponed_evaluation_as_immediate(self) -> None:
        scheduled_for = datetime.fromisoformat("2026-04-14T21:30:00+02:00")
        hard_cutoff_at = datetime.fromisoformat("2026-04-15T01:00:00+02:00")
        self.db.set_service_state(
            POSTPONED_EVALUATION_STATE_KEY,
            {
                "scheduled_for": scheduled_for.isoformat(),
                "hard_cutoff_at": hard_cutoff_at.isoformat(),
                "reason": "QUIET_WINDOW_NOT_MET",
                "quiet_window": {},
            },
            updated_at_iso=self.now.isoformat(),
        )

        self.service._reconcile_startup_state()

        expected_run_time = self.now + timedelta(seconds=RECONCILIATION_GRACE_SECONDS)
        job = self.service.scheduler.get_job(POSTPONED_EVALUATION_JOB_ID)
        self.assertIsNotNone(job)
        self.assertEqual(job.trigger.run_date.isoformat(), expected_run_time.isoformat())
        state = self.db.get_service_state(POSTPONED_EVALUATION_STATE_KEY)
        self.assertIsNotNone(state)
        self.assertEqual(state["scheduled_for"], expected_run_time.isoformat())

    def test_clears_expired_postponed_evaluation(self) -> None:
        scheduled_for = datetime.fromisoformat("2026-04-14T22:30:00+02:00")
        hard_cutoff_at = datetime.fromisoformat("2026-04-14T21:00:00+02:00")
        self.db.set_service_state(
            POSTPONED_EVALUATION_STATE_KEY,
            {
                "scheduled_for": scheduled_for.isoformat(),
                "hard_cutoff_at": hard_cutoff_at.isoformat(),
                "reason": "NO_TELEMETRY_RECEIVED",
                "quiet_window": {},
            },
            updated_at_iso=self.now.isoformat(),
        )

        self.service._reconcile_startup_state()

        self.assertIsNone(self.service.scheduler.get_job(POSTPONED_EVALUATION_JOB_ID))
        self.assertIsNone(self.db.get_service_state(POSTPONED_EVALUATION_STATE_KEY))


if __name__ == "__main__":
    unittest.main()