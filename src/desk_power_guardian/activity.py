from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .config import Settings


class PowerSampleLike(Protocol):
    created_at: datetime
    power_watts: float


@dataclass(frozen=True)
class ActivityAssessment:
    state: str
    reason: str
    power_watts: float | None
    sample_age_seconds: float | None
    sample_time: str | None


class ActivityClassifier:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def assess_latest(self, sample: PowerSampleLike | None, now: datetime) -> ActivityAssessment:
        if sample is None:
            return ActivityAssessment(
                state="NO_DATA",
                reason="NO_TELEMETRY_RECEIVED",
                power_watts=None,
                sample_age_seconds=None,
                sample_time=None,
            )

        sample_age_seconds = max((now - sample.created_at).total_seconds(), 0.0)
        if sample_age_seconds > self._settings.telemetry_stale_seconds:
            return ActivityAssessment(
                state="STALE",
                reason="TELEMETRY_TOO_OLD",
                power_watts=sample.power_watts,
                sample_age_seconds=sample_age_seconds,
                sample_time=sample.created_at.isoformat(),
            )

        if sample.power_watts >= self._settings.active_watts_threshold:
            return ActivityAssessment(
                state="ACTIVE",
                reason="POWER_AT_OR_ABOVE_ACTIVE_THRESHOLD",
                power_watts=sample.power_watts,
                sample_age_seconds=sample_age_seconds,
                sample_time=sample.created_at.isoformat(),
            )

        if sample.power_watts <= self._settings.idle_watts_threshold:
            return ActivityAssessment(
                state="IDLE",
                reason="POWER_AT_OR_BELOW_IDLE_THRESHOLD",
                power_watts=sample.power_watts,
                sample_age_seconds=sample_age_seconds,
                sample_time=sample.created_at.isoformat(),
            )

        return ActivityAssessment(
            state="UNCERTAIN",
            reason="POWER_BETWEEN_IDLE_AND_ACTIVE_THRESHOLDS",
            power_watts=sample.power_watts,
            sample_age_seconds=sample_age_seconds,
            sample_time=sample.created_at.isoformat(),
        )