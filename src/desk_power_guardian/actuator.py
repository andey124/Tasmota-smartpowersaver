from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote
from urllib.request import urlopen

import paho.mqtt.client as mqtt

from .config import Settings

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ActuationResult:
    success: bool
    mode: str
    detail: str


class TasmotaActuator:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._mqtt_client = mqtt.Client(protocol=mqtt.MQTTv311)
        if not settings.mqtt_allow_anonymous and settings.mqtt_username:
            self._mqtt_client.username_pw_set(settings.mqtt_username, settings.mqtt_password)

    def _publish_mqtt(self, payload: str) -> ActuationResult:
        topic = self._settings.command_topic
        try:
            self._mqtt_client.connect(self._settings.mqtt_host, self._settings.mqtt_port, keepalive=10)
            info = self._mqtt_client.publish(topic, payload=payload, qos=0, retain=False)
            self._mqtt_client.disconnect()
            if info.rc != mqtt.MQTT_ERR_SUCCESS:
                return ActuationResult(False, "mqtt", f"publish failed rc={info.rc}")
            return ActuationResult(True, "mqtt", f"published {payload} to {topic}")
        except Exception as exc:  # pragma: no cover
            LOGGER.exception("MQTT publish failed")
            return ActuationResult(False, "mqtt", str(exc))

    def _publish_http(self, payload: str) -> ActuationResult:
        if not self._settings.http_fallback_url:
            return ActuationResult(False, "http", "http fallback not configured")
        base = self._settings.http_fallback_url.rstrip("/")
        command = quote(f"Power {payload}")
        url = f"{base}/cm?cmnd={command}"
        try:
            with urlopen(url, timeout=5) as response:  # nosec B310
                status = getattr(response, "status", 200)
            if status >= 400:
                return ActuationResult(False, "http", f"http status={status}")
            return ActuationResult(True, "http", f"called {url}")
        except Exception as exc:  # pragma: no cover
            LOGGER.exception("HTTP fallback failed")
            return ActuationResult(False, "http", str(exc))

    def send_power(self, power_state: str, reason: str) -> ActuationResult:
        payload = power_state.upper()
        if self._settings.dry_run:
            return ActuationResult(
                True,
                "dry_run",
                f"would publish {payload} to {self._settings.command_topic} (reason={reason})",
            )

        mqtt_result = self._publish_mqtt(payload)
        if mqtt_result.success:
            return mqtt_result

        http_result = self._publish_http(payload)
        if http_result.success:
            return http_result

        detail = f"mqtt={mqtt_result.detail}; http={http_result.detail}"
        return ActuationResult(False, "fallback_failed", detail)
