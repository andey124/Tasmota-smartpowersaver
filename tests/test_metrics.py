from __future__ import annotations

import unittest
from datetime import datetime

from desk_power_guardian.config import Settings
from desk_power_guardian.db import Database
from desk_power_guardian.metrics import render_metrics
from desk_power_guardian.service import GuardianService


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


class MetricsRenderingTests(unittest.TestCase):
    def test_renders_prometheus_counters_and_gauges(self) -> None:
        settings = build_settings()
        db = Database(":memory:")
        db.init_schema()
        service = GuardianService(settings=settings, db=db)

        db.log_event("EVALUATION", {}, "2026-04-14T20:00:00+02:00")
        db.log_event("POSTPONED_EVALUATION_SCHEDULED", {}, "2026-04-14T20:00:01+02:00")
        db.log_event("OFF_TRIGGERED", {}, "2026-04-14T20:30:00+02:00")
        db.log_event("HARD_CUTOFF_USED", {}, "2026-04-15T01:00:00+02:00")

        metrics = render_metrics(service)

        self.assertIn("desk_power_guardian_evaluations_total 1", metrics)
        self.assertIn("desk_power_guardian_postpones_total 1", metrics)
        self.assertIn("desk_power_guardian_offs_total 2", metrics)
        self.assertIn("desk_power_guardian_override_active 0", metrics)
        self.assertIn("desk_power_guardian_latest_power_watts NaN", metrics)

        db.close()


if __name__ == "__main__":
    unittest.main()