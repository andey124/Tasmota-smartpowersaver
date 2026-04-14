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


@dataclass(frozen=True)
class QuietWindowAssessment:
    off_allowed: bool
    reason: str
    quiet_for_seconds: float
    quiet_minutes_required: int
    latest_state: str
    latest_power_watts: float | None
    latest_sample_time: str | None
    idle_since: str | None
    considered_samples: int


class ActivityClassifier:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def classify_power(self, power_watts: float) -> str:
        if power_watts >= self._settings.active_watts_threshold:
            return "ACTIVE"
        if power_watts <= self._settings.idle_watts_threshold:
            return "IDLE"
        return "UNCERTAIN"

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

        state = self.classify_power(sample.power_watts)
        if state == "ACTIVE":
            return ActivityAssessment(
                state="ACTIVE",
                reason="POWER_AT_OR_ABOVE_ACTIVE_THRESHOLD",
                power_watts=sample.power_watts,
                sample_age_seconds=sample_age_seconds,
                sample_time=sample.created_at.isoformat(),
            )

        if state == "IDLE":
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

    def assess_quiet_window(self, samples: list[PowerSampleLike], now: datetime) -> QuietWindowAssessment:
        required_seconds = float(self._settings.quiet_minutes_required * 60)
        if not samples:
            return QuietWindowAssessment(
                off_allowed=False,
                reason="NO_TELEMETRY_RECEIVED",
                quiet_for_seconds=0.0,
                quiet_minutes_required=self._settings.quiet_minutes_required,
                latest_state="NO_DATA",
                latest_power_watts=None,
                latest_sample_time=None,
                idle_since=None,
                considered_samples=0,
            )

        ordered_samples = sorted(samples, key=lambda sample: sample.created_at)
        latest_sample = ordered_samples[-1]
        latest_assessment = self.assess_latest(latest_sample, now=now)
        if latest_assessment.state != "IDLE":
            return QuietWindowAssessment(
                off_allowed=False,
                reason=latest_assessment.reason,
                quiet_for_seconds=0.0,
                quiet_minutes_required=self._settings.quiet_minutes_required,
                latest_state=latest_assessment.state,
                latest_power_watts=latest_assessment.power_watts,
                latest_sample_time=latest_assessment.sample_time,
                idle_since=None,
                considered_samples=1,
            )

        idle_since = latest_sample.created_at
        considered_samples = 1
        next_sample_time = latest_sample.created_at

        for sample in reversed(ordered_samples[:-1]):
            gap_seconds = (next_sample_time - sample.created_at).total_seconds()
            if gap_seconds > self._settings.telemetry_stale_seconds:
                break

            sample_state = self.classify_power(sample.power_watts)
            if sample_state != "IDLE":
                break

            idle_since = sample.created_at
            next_sample_time = sample.created_at
            considered_samples += 1

        quiet_for_seconds = max((now - idle_since).total_seconds(), 0.0)
        if quiet_for_seconds >= required_seconds:
            return QuietWindowAssessment(
                off_allowed=True,
                reason="QUIET_WINDOW_MET",
                quiet_for_seconds=quiet_for_seconds,
                quiet_minutes_required=self._settings.quiet_minutes_required,
                latest_state=latest_assessment.state,
                latest_power_watts=latest_assessment.power_watts,
                latest_sample_time=latest_assessment.sample_time,
                idle_since=idle_since.isoformat(),
                considered_samples=considered_samples,
            )

        return QuietWindowAssessment(
            off_allowed=False,
            reason="QUIET_WINDOW_NOT_MET",
            quiet_for_seconds=quiet_for_seconds,
            quiet_minutes_required=self._settings.quiet_minutes_required,
            latest_state=latest_assessment.state,
            latest_power_watts=latest_assessment.power_watts,
            latest_sample_time=latest_assessment.sample_time,
            idle_since=idle_since.isoformat(),
            considered_samples=considered_samples,
        )