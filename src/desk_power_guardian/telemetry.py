from __future__ import annotations

import json
import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

import paho.mqtt.client as mqtt

from .config import Settings
from .db import Database

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class TelemetrySample:
    created_at: datetime
    topic: str
    power_watts: float
    payload: dict


class TelemetryCollector:
    def __init__(self, settings: Settings, db: Database, now_provider: Callable[[], datetime]) -> None:
        self._settings = settings
        self._db = db
        self._now_provider = now_provider
        self._samples: deque[TelemetrySample] = deque(maxlen=settings.telemetry_window_size)
        self._mqtt_client = mqtt.Client(protocol=mqtt.MQTTv311)
        if not settings.mqtt_allow_anonymous and settings.mqtt_username:
            self._mqtt_client.username_pw_set(settings.mqtt_username, settings.mqtt_password)

        self._mqtt_client.on_connect = self._on_connect
        self._mqtt_client.on_message = self._on_message
        self._running = False

    def start(self) -> None:
        try:
            self._mqtt_client.connect(self._settings.mqtt_host, self._settings.mqtt_port, keepalive=30)
            self._mqtt_client.loop_start()
            self._running = True
            LOGGER.info("telemetry collector started topic=%s", self._settings.telemetry_topic)
        except Exception:
            LOGGER.exception("failed to start telemetry collector")

    def stop(self) -> None:
        if not self._running:
            return

        try:
            self._mqtt_client.loop_stop()
            self._mqtt_client.disconnect()
        except Exception:
            LOGGER.exception("failed to stop telemetry collector cleanly")
        finally:
            self._running = False

    def status(self) -> dict:
        latest = self.latest_sample()
        return {
            "topic": self._settings.telemetry_topic,
            "window_size": self._settings.telemetry_window_size,
            "db_retention": self._settings.telemetry_db_retention,
            "sample_count": len(self._samples),
            "latest_sample": None
            if latest is None
            else {
                "created_at": latest.created_at.isoformat(),
                "topic": latest.topic,
                "power_watts": latest.power_watts,
            },
        }

    def latest_sample(self) -> TelemetrySample | None:
        if not self._samples:
            return None
        return self._samples[-1]

    def recent_samples(self, limit: int = 10) -> list[TelemetrySample]:
        if limit <= 0:
            return []
        return list(self._samples)[-limit:]

    def _on_connect(self, client: mqtt.Client, userdata: object, flags: dict, rc: int) -> None:
        if rc != mqtt.MQTT_ERR_SUCCESS:
            LOGGER.warning("telemetry collector connect failed rc=%s", rc)
            return
        client.subscribe(self._settings.telemetry_topic, qos=0)
        LOGGER.info("telemetry collector subscribed topic=%s", self._settings.telemetry_topic)

    def _on_message(self, client: mqtt.Client, userdata: object, msg: mqtt.MQTTMessage) -> None:
        sample = self._parse_message(msg.topic, msg.payload)
        if sample is None:
            return

        self._samples.append(sample)
        if self._settings.telemetry_db_retention > 0:
            self._db.log_power_sample(
                created_at_iso=sample.created_at.isoformat(),
                topic=sample.topic,
                power_watts=sample.power_watts,
                payload=sample.payload,
                retention_limit=self._settings.telemetry_db_retention,
            )

    def _parse_message(self, topic: str, raw_payload: bytes) -> TelemetrySample | None:
        try:
            payload = json.loads(raw_payload.decode("utf-8"))
        except Exception:
            LOGGER.debug("ignoring telemetry message with invalid JSON topic=%s", topic)
            return None

        energy = payload.get("ENERGY")
        if not isinstance(energy, dict):
            LOGGER.debug("ignoring telemetry message without ENERGY payload topic=%s", topic)
            return None

        power_value = energy.get("Power")
        if power_value is None:
            LOGGER.debug("ignoring telemetry message without ENERGY.Power topic=%s", topic)
            return None

        try:
            power_watts = float(power_value)
        except (TypeError, ValueError):
            LOGGER.debug("ignoring telemetry message with invalid power value topic=%s", topic)
            return None

        created_at = self._extract_timestamp(payload)
        return TelemetrySample(
            created_at=created_at,
            topic=topic,
            power_watts=power_watts,
            payload=payload,
        )

    def _extract_timestamp(self, payload: dict) -> datetime:
        payload_time = payload.get("Time")
        if isinstance(payload_time, str):
            try:
                return datetime.fromisoformat(payload_time)
            except ValueError:
                LOGGER.debug("telemetry payload time was not ISO formatted: %s", payload_time)
        return self._now_provider()