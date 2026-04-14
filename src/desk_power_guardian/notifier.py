from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable
from urllib.request import Request, urlopen

from .config import Settings


@dataclass(frozen=True)
class NotificationResult:
    attempted: bool
    success: bool
    detail: str
    delay_seconds: int
    planned_shutdown_at: str


class ShutdownNotifier:
    def __init__(
        self,
        settings: Settings,
        opener: Callable[..., object] = urlopen,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._settings = settings
        self._opener = opener
        self._sleeper = sleeper

    def notify_pre_shutdown(
        self,
        now: datetime,
        reason: str,
        hard_cutoff_at: datetime | None,
        dry_run: bool,
    ) -> NotificationResult:
        delay_seconds = max(self._settings.pre_shutdown_notify_delay_seconds, 0)
        planned_shutdown_at = now + timedelta(seconds=delay_seconds)
        if not self._settings.notification_webhook_url:
            return NotificationResult(
                attempted=False,
                success=False,
                detail="notification webhook not configured",
                delay_seconds=delay_seconds,
                planned_shutdown_at=planned_shutdown_at.isoformat(),
            )

        payload = {
            "event": "PRE_SHUTDOWN",
            "service": "desk-power-guardian",
            "reason": reason,
            "dry_run": dry_run,
            "delay_seconds": delay_seconds,
            "notified_at": now.isoformat(),
            "planned_shutdown_at": planned_shutdown_at.isoformat(),
            "hard_cutoff_at": None if hard_cutoff_at is None else hard_cutoff_at.isoformat(),
            "command_topic": self._settings.command_topic,
            "command_payload": "OFF",
        }
        request = Request(
            self._settings.notification_webhook_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._opener(request, timeout=self._settings.notification_timeout_seconds) as response:  # nosec B310
                status = getattr(response, "status", 200)
            if status >= 400:
                detail = f"notification webhook status={status}"
                return NotificationResult(True, False, detail, delay_seconds, planned_shutdown_at.isoformat())
            if delay_seconds > 0:
                self._sleeper(delay_seconds)
            return NotificationResult(True, True, "notification delivered", delay_seconds, planned_shutdown_at.isoformat())
        except Exception as exc:
            return NotificationResult(True, False, str(exc), delay_seconds, planned_shutdown_at.isoformat())