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
    mqtt_host: str
    mqtt_port: int
    mqtt_allow_anonymous: bool
    mqtt_username: str | None
    mqtt_password: str | None
    tasmota_base_topic: str
    tasmota_command_prefix: str
    http_fallback_url: str | None
    sqlite_path: str

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.tz)

    @property
    def command_topic(self) -> str:
        return f"{self.tasmota_command_prefix}/{self.tasmota_base_topic}/POWER"


def load_settings() -> Settings:
    tz = _env("TZ", "Europe/Berlin") or "Europe/Berlin"
    dry_run = _to_bool(_env("DRY_RUN", "true"), default=True)
    auto_off_time = _parse_time(_env("AUTO_OFF_TIME", "20:00") or "20:00", "AUTO_OFF_TIME")
    reset_time = _parse_time(_env("OVERRIDE_RESET_TIME", "00:05") or "00:05", "OVERRIDE_RESET_TIME")
    hard_cutoff_time = _parse_time(_env("HARD_CUTOFF_TIME", "01:00") or "01:00", "HARD_CUTOFF_TIME")
    mqtt_host = _env("MQTT_HOST", "127.0.0.1") or "127.0.0.1"
    mqtt_port = int(_env("MQTT_PORT", "1883") or "1883")
    mqtt_allow_anonymous = _to_bool(_env("MQTT_ALLOW_ANONYMOUS", "true"), default=True)
    mqtt_username = _env("MQTT_USERNAME")
    mqtt_password = _env("MQTT_PASSWORD")
    tasmota_base_topic = _env("TASMOTA_BASE_TOPIC", "tasmota_1C8D21") or "tasmota_1C8D21"
    tasmota_command_prefix = _env("TASMOTA_COMMAND_PREFIX", "cmnd") or "cmnd"
    http_fallback_url = _env("HTTP_FALLBACK_URL")
    sqlite_path = _env("SQLITE_PATH", "data/desk_power_guardian.db") or "data/desk_power_guardian.db"

    return Settings(
        tz=tz,
        dry_run=dry_run,
        auto_off_time=auto_off_time,
        reset_time=reset_time,
        hard_cutoff_time=hard_cutoff_time,
        mqtt_host=mqtt_host,
        mqtt_port=mqtt_port,
        mqtt_allow_anonymous=mqtt_allow_anonymous,
        mqtt_username=mqtt_username,
        mqtt_password=mqtt_password,
        tasmota_base_topic=tasmota_base_topic,
        tasmota_command_prefix=tasmota_command_prefix,
        http_fallback_url=http_fallback_url,
        sqlite_path=sqlite_path,
    )
