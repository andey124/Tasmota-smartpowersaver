from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import paho.mqtt.client as mqtt

from .activity import ActivityClassifier
from .config import Settings
from .telemetry import TelemetrySample, parse_telemetry_message


@dataclass(frozen=True)
class SimulatedDecision:
    outcome: str
    reason: str
    details: dict[str, Any]


def build_mqtt_client(settings: Settings, client_id_prefix: str) -> mqtt.Client:
    client_id = f"{client_id_prefix}-{uuid.uuid4().hex[:8]}"
    client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)
    if not settings.mqtt_allow_anonymous and settings.mqtt_username:
        client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
    return client


def decode_json_payload(raw_payload: bytes) -> Any | None:
    try:
        return json.loads(raw_payload.decode("utf-8"))
    except Exception:
        return None


def payload_text(raw_payload: bytes) -> str:
    return raw_payload.decode("utf-8", errors="replace").strip()


def summarize_probe_message(
    topic: str,
    raw_payload: bytes,
    settings: Settings,
    now_provider: callable,
) -> tuple[bool, str]:
    telemetry = parse_telemetry_message(topic, raw_payload, settings, now_provider)
    if telemetry is not None:
        summary = (
            f"SENSOR power={telemetry.power_watts:.2f}W "
            f"time={telemetry.created_at.isoformat()} topic={topic}"
        )
        return True, summary

    suffix = topic.rsplit("/", 1)[-1].upper()
    decoded = decode_json_payload(raw_payload)
    if suffix == "STATE" and isinstance(decoded, dict):
        power_state = decoded.get("POWER")
        wifi = decoded.get("Wifi", {}) if isinstance(decoded.get("Wifi"), dict) else {}
        summary = (
            f"STATE power={power_state!s} signal={wifi.get('RSSI', 'n/a')} topic={topic}"
        )
        return topic.startswith(f"{settings.telemetry_topic_prefix}/"), summary

    if suffix == "POWER":
        return topic.startswith(f"{settings.telemetry_topic_prefix}/"), f"POWER state={payload_text(raw_payload)} topic={topic}"

    if isinstance(decoded, dict):
        preview = json.dumps(decoded, separators=(",", ":"))[:180]
        return topic.startswith(f"{settings.telemetry_topic_prefix}/"), f"{suffix} json={preview} topic={topic}"

    return topic.startswith(f"{settings.telemetry_topic_prefix}/"), f"{suffix} raw={payload_text(raw_payload)[:180]} topic={topic}"


def current_cycle_window(settings: Settings, now: datetime) -> tuple[datetime, datetime]:
    auto_off_time = settings.auto_off_time
    cutoff_time = settings.hard_cutoff_time

    if auto_off_time > cutoff_time:
        if now.time() >= auto_off_time:
            window_start = now.replace(hour=auto_off_time.hour, minute=auto_off_time.minute, second=0, microsecond=0)
            window_cutoff = (window_start + timedelta(days=1)).replace(
                hour=cutoff_time.hour,
                minute=cutoff_time.minute,
                second=0,
                microsecond=0,
            )
            return window_start, window_cutoff

        if now.time() < cutoff_time:
            window_cutoff = now.replace(hour=cutoff_time.hour, minute=cutoff_time.minute, second=0, microsecond=0)
            window_start = (window_cutoff - timedelta(days=1)).replace(
                hour=auto_off_time.hour,
                minute=auto_off_time.minute,
                second=0,
                microsecond=0,
            )
            return window_start, window_cutoff

        window_start = now.replace(hour=auto_off_time.hour, minute=auto_off_time.minute, second=0, microsecond=0)
        window_cutoff = (window_start + timedelta(days=1)).replace(
            hour=cutoff_time.hour,
            minute=cutoff_time.minute,
            second=0,
            microsecond=0,
        )
        return window_start, window_cutoff

    window_start = now.replace(hour=auto_off_time.hour, minute=auto_off_time.minute, second=0, microsecond=0)
    window_cutoff = now.replace(hour=cutoff_time.hour, minute=cutoff_time.minute, second=0, microsecond=0)
    if now < window_start:
        return window_start, window_cutoff
    return window_start, window_cutoff


def evaluate_simulated_decision(
    settings: Settings,
    classifier: ActivityClassifier,
    samples: list[TelemetrySample],
    now: datetime,
    override_today: bool,
) -> SimulatedDecision:
    window_start, window_cutoff = current_cycle_window(settings, now)
    if now < window_start:
        return SimulatedDecision(
            outcome="BEFORE_AUTO_OFF",
            reason="WAITING_FOR_AUTO_OFF_WINDOW",
            details={
                "window_start": window_start.isoformat(),
                "window_cutoff": window_cutoff.isoformat(),
            },
        )

    if now >= window_cutoff:
        return SimulatedDecision(
            outcome="HARD_CUTOFF_USED",
            reason="HARD_CUTOFF_TIME_REACHED",
            details={
                "window_start": window_start.isoformat(),
                "window_cutoff": window_cutoff.isoformat(),
                "command_topic": settings.command_topic,
                "command_payload": "OFF",
            },
        )

    if override_today:
        return SimulatedDecision(
            outcome="OVERRIDE_ACTIVE",
            reason="OVERRIDE_SET_FOR_TODAY",
            details={
                "window_start": window_start.isoformat(),
                "window_cutoff": window_cutoff.isoformat(),
            },
        )

    quiet_window = classifier.assess_quiet_window(samples, now=now)
    details = {
        "window_start": window_start.isoformat(),
        "window_cutoff": window_cutoff.isoformat(),
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
    }
    if quiet_window.off_allowed:
        details["command_topic"] = settings.command_topic
        details["command_payload"] = "OFF"
        return SimulatedDecision(outcome="OFF_ALLOWED", reason="QUIET_WINDOW_MET", details=details)

    if quiet_window.latest_state == "ACTIVE":
        return SimulatedDecision(outcome="POSTPONED_ACTIVE", reason=quiet_window.reason, details=details)

    return SimulatedDecision(outcome="POSTPONED_WAITING_IDLE", reason=quiet_window.reason, details=details)