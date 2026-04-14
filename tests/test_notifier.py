from __future__ import annotations

import json
import unittest
from datetime import datetime

from desk_power_guardian.config import Settings
from desk_power_guardian.notifier import ShutdownNotifier


class FakeResponse:
    def __init__(self, status: int = 200) -> None:
        self.status = status

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def build_settings(webhook_url: str | None, delay_seconds: int = 0) -> Settings:
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
        notification_webhook_url=webhook_url,
        notification_timeout_seconds=5,
        pre_shutdown_notify_delay_seconds=delay_seconds,
        sqlite_path=":memory:",
    )


class ShutdownNotifierTests(unittest.TestCase):
    def test_skips_when_webhook_is_not_configured(self) -> None:
        notifier = ShutdownNotifier(build_settings(None))
        result = notifier.notify_pre_shutdown(
            now=datetime.fromisoformat("2026-04-14T20:00:00+02:00"),
            reason="SCHEDULED_AUTO_OFF",
            hard_cutoff_at=datetime.fromisoformat("2026-04-15T01:00:00+02:00"),
            dry_run=True,
        )
        self.assertFalse(result.attempted)
        self.assertFalse(result.success)

    def test_posts_json_payload_and_honors_delay(self) -> None:
        captured: dict[str, object] = {}
        slept: list[float] = []

        def opener(request, timeout):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse(200)

        notifier = ShutdownNotifier(
            build_settings("https://example.test/hook", delay_seconds=3),
            opener=opener,
            sleeper=lambda seconds: slept.append(seconds),
        )
        now = datetime.fromisoformat("2026-04-14T20:00:00+02:00")
        result = notifier.notify_pre_shutdown(
            now=now,
            reason="SCHEDULED_AUTO_OFF",
            hard_cutoff_at=datetime.fromisoformat("2026-04-15T01:00:00+02:00"),
            dry_run=True,
        )

        self.assertTrue(result.attempted)
        self.assertTrue(result.success)
        self.assertEqual(captured["url"], "https://example.test/hook")
        self.assertEqual(captured["timeout"], 5)
        self.assertEqual(captured["payload"]["reason"], "SCHEDULED_AUTO_OFF")
        self.assertEqual(captured["payload"]["delay_seconds"], 3)
        self.assertEqual(captured["payload"]["command_topic"], "cmnd/tasmota_1C8D21/POWER")
        self.assertEqual(slept, [3])


if __name__ == "__main__":
    unittest.main()