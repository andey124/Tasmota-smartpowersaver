from __future__ import annotations

import unittest
from dataclasses import dataclass
from datetime import datetime, timedelta

from desk_power_guardian.activity import ActivityClassifier
from desk_power_guardian.config import Settings


@dataclass(frozen=True)
class Sample:
    created_at: datetime
    power_watts: float


class ActivityClassifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(
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
            telemetry_topic_prefix="tele",
            telemetry_sensor_suffix="SENSOR",
            telemetry_window_size=120,
            telemetry_db_retention=500,
            http_fallback_url=None,
            sqlite_path=":memory:",
        )
        self.classifier = ActivityClassifier(self.settings)
        self.now = datetime(2026, 4, 14, 20, 0, 0)

    def test_returns_no_data_when_sample_is_missing(self) -> None:
        result = self.classifier.assess_latest(None, now=self.now)
        self.assertEqual(result.state, "NO_DATA")
        self.assertEqual(result.reason, "NO_TELEMETRY_RECEIVED")

    def test_marks_exact_active_threshold_as_active(self) -> None:
        result = self.classifier.assess_latest(
            Sample(created_at=self.now - timedelta(seconds=30), power_watts=45.0),
            now=self.now,
        )
        self.assertEqual(result.state, "ACTIVE")

    def test_marks_exact_idle_threshold_as_idle(self) -> None:
        result = self.classifier.assess_latest(
            Sample(created_at=self.now - timedelta(seconds=30), power_watts=20.0),
            now=self.now,
        )
        self.assertEqual(result.state, "IDLE")

    def test_marks_between_thresholds_as_uncertain(self) -> None:
        result = self.classifier.assess_latest(
            Sample(created_at=self.now - timedelta(seconds=30), power_watts=32.5),
            now=self.now,
        )
        self.assertEqual(result.state, "UNCERTAIN")

    def test_marks_old_sample_as_stale(self) -> None:
        result = self.classifier.assess_latest(
            Sample(created_at=self.now - timedelta(seconds=901), power_watts=10.0),
            now=self.now,
        )
        self.assertEqual(result.state, "STALE")
        self.assertEqual(result.reason, "TELEMETRY_TOO_OLD")

    def test_normalizes_naive_sample_times(self) -> None:
        naive_sample_time = datetime(2026, 4, 14, 19, 59, 30)
        result = self.classifier.assess_latest(
            Sample(created_at=naive_sample_time, power_watts=20.0),
            now=self.now,
        )
        self.assertEqual(result.state, "IDLE")
        self.assertEqual(result.sample_time, "2026-04-14T19:59:30+02:00")

    def test_quiet_window_allows_off_after_continuous_idle(self) -> None:
        result = self.classifier.assess_quiet_window(
            [
                Sample(created_at=self.now - timedelta(minutes=21), power_watts=10.0),
                Sample(created_at=self.now - timedelta(minutes=10), power_watts=12.0),
                Sample(created_at=self.now - timedelta(minutes=1), power_watts=15.0),
            ],
            now=self.now,
        )
        self.assertTrue(result.off_allowed)
        self.assertEqual(result.reason, "QUIET_WINDOW_MET")

    def test_quiet_window_blocks_recent_activity(self) -> None:
        result = self.classifier.assess_quiet_window(
            [
                Sample(created_at=self.now - timedelta(minutes=25), power_watts=10.0),
                Sample(created_at=self.now - timedelta(minutes=5), power_watts=55.0),
                Sample(created_at=self.now - timedelta(minutes=1), power_watts=10.0),
            ],
            now=self.now,
        )
        self.assertFalse(result.off_allowed)
        self.assertEqual(result.reason, "QUIET_WINDOW_NOT_MET")

    def test_quiet_window_blocks_when_latest_sample_is_uncertain(self) -> None:
        result = self.classifier.assess_quiet_window(
            [
                Sample(created_at=self.now - timedelta(minutes=3), power_watts=30.0),
            ],
            now=self.now,
        )
        self.assertFalse(result.off_allowed)
        self.assertEqual(result.reason, "POWER_BETWEEN_IDLE_AND_ACTIVE_THRESHOLDS")

    def test_quiet_window_breaks_on_large_gap(self) -> None:
        result = self.classifier.assess_quiet_window(
            [
                Sample(created_at=self.now - timedelta(minutes=20), power_watts=10.0),
                Sample(created_at=self.now - timedelta(minutes=1), power_watts=10.0),
            ],
            now=self.now,
        )
        self.assertFalse(result.off_allowed)
        self.assertEqual(result.reason, "QUIET_WINDOW_NOT_MET")


if __name__ == "__main__":
    unittest.main()