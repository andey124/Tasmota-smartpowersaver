from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import time
from zoneinfo import ZoneInfo


def _clean_env(value: str | None) -> str | None:
    if value is None:
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    return trimmed.strip("`\"'")


def _env(name: str, default: str | None = None) -> str | None:
    raw = os.getenv(name)
    cleaned = _clean_env(raw)
    if cleaned is not None:
        return cleaned
    return default


def _to_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _parse_time(text: str, var_name: str) -> time:
    parts = text.split(":")
    if len(parts) != 2:
        raise ValueError(f"{var_name} must be HH:MM")
    hour = int(parts[0])
    minute = int(parts[1])
    return time(hour=hour, minute=minute)


@dataclass(frozen=True)
class Settings:
    tz: str
    dry_run: bool
    auto_off_time: time
    reset_time: time
    hard_cutoff_time: time
    active_watts_threshold: float
    idle_watts_threshold: float
    quiet_minutes_required: int
    telemetry_stale_seconds: int
    mqtt_host: str
    mqtt_port: int
    mqtt_allow_anonymous: bool
    mqtt_username: str | None
    mqtt_password: str | None
    tasmota_base_topic: str
    tasmota_command_prefix: str
    telemetry_topic_prefix: str
    telemetry_sensor_suffix: str
    telemetry_window_size: int
    telemetry_db_retention: int
    http_fallback_url: str | None
    sqlite_path: str

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.tz)

    @property
    def command_topic(self) -> str:
        return f"{self.tasmota_command_prefix}/{self.tasmota_base_topic}/POWER"

    @property
    def telemetry_topic(self) -> str:
        return f"{self.telemetry_topic_prefix}/{self.tasmota_base_topic}/{self.telemetry_sensor_suffix}"


def load_settings() -> Settings:
    tz = _env("TZ", "Europe/Berlin") or "Europe/Berlin"
    dry_run = _to_bool(_env("DRY_RUN", "true"), default=True)
    auto_off_time = _parse_time(_env("AUTO_OFF_TIME", "20:00") or "20:00", "AUTO_OFF_TIME")
    reset_time = _parse_time(_env("OVERRIDE_RESET_TIME", "00:05") or "00:05", "OVERRIDE_RESET_TIME")
    hard_cutoff_time = _parse_time(_env("HARD_CUTOFF_TIME", "01:00") or "01:00", "HARD_CUTOFF_TIME")
    active_watts_threshold = float(_env("ACTIVE_WATTS_THRESHOLD", "45") or "45")
    idle_watts_threshold = float(_env("IDLE_WATTS_THRESHOLD", "20") or "20")
    quiet_minutes_required = int(_env("QUIET_MINUTES_REQUIRED", "20") or "20")
    telemetry_stale_seconds = int(_env("TELEMETRY_STALE_SECONDS", "900") or "900")
    mqtt_host = _env("MQTT_HOST", "127.0.0.1") or "127.0.0.1"
    mqtt_port = int(_env("MQTT_PORT", "1883") or "1883")
    mqtt_allow_anonymous = _to_bool(_env("MQTT_ALLOW_ANONYMOUS", "true"), default=True)
    mqtt_username = _env("MQTT_USERNAME")
    mqtt_password = _env("MQTT_PASSWORD")
    tasmota_base_topic = _env("TASMOTA_BASE_TOPIC", "tasmota_1C8D21") or "tasmota_1C8D21"
    tasmota_command_prefix = _env("TASMOTA_COMMAND_PREFIX", "cmnd") or "cmnd"
    telemetry_topic_prefix = _env("TELEMETRY_TOPIC_PREFIX", "tele") or "tele"
    telemetry_sensor_suffix = _env("TELEMETRY_SENSOR_SUFFIX", "SENSOR") or "SENSOR"
    telemetry_window_size = int(_env("TELEMETRY_WINDOW_SIZE", "120") or "120")
    telemetry_db_retention = int(_env("TELEMETRY_DB_RETENTION", "500") or "500")
    http_fallback_url = _env("HTTP_FALLBACK_URL")
    sqlite_path = _env("SQLITE_PATH", "data/desk_power_guardian.db") or "data/desk_power_guardian.db"

    if idle_watts_threshold > active_watts_threshold:
        raise ValueError("IDLE_WATTS_THRESHOLD must be less than or equal to ACTIVE_WATTS_THRESHOLD")

    return Settings(
        tz=tz,
        dry_run=dry_run,
        auto_off_time=auto_off_time,
        reset_time=reset_time,
        hard_cutoff_time=hard_cutoff_time,
        active_watts_threshold=active_watts_threshold,
        idle_watts_threshold=idle_watts_threshold,
        quiet_minutes_required=quiet_minutes_required,
        telemetry_stale_seconds=telemetry_stale_seconds,
        mqtt_host=mqtt_host,
        mqtt_port=mqtt_port,
        mqtt_allow_anonymous=mqtt_allow_anonymous,
        mqtt_username=mqtt_username,
        mqtt_password=mqtt_password,
        tasmota_base_topic=tasmota_base_topic,
        tasmota_command_prefix=tasmota_command_prefix,
        telemetry_topic_prefix=telemetry_topic_prefix,
        telemetry_sensor_suffix=telemetry_sensor_suffix,
        telemetry_window_size=telemetry_window_size,
        telemetry_db_retention=telemetry_db_retention,
        http_fallback_url=http_fallback_url,
        sqlite_path=sqlite_path,
    )
