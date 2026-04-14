from __future__ import annotations

from .service import GuardianService


def render_metrics(service: GuardianService) -> str:
    event_counts = service.db.count_events_by_type(
        [
            "EVALUATION",
            "POSTPONED_EVALUATION_SCHEDULED",
            "OFF_TRIGGERED",
            "HARD_CUTOFF_USED",
        ]
    )
    decision = service.decision_context()

    metrics = [
        "# HELP desk_power_guardian_evaluations_total Total automatic evaluation runs.",
        "# TYPE desk_power_guardian_evaluations_total counter",
        f"desk_power_guardian_evaluations_total {event_counts['EVALUATION']}",
        "# HELP desk_power_guardian_postpones_total Total postponed evaluation schedules.",
        "# TYPE desk_power_guardian_postpones_total counter",
        f"desk_power_guardian_postpones_total {event_counts['POSTPONED_EVALUATION_SCHEDULED']}",
        "# HELP desk_power_guardian_offs_total Total automated power-off actions including hard cutoff.",
        "# TYPE desk_power_guardian_offs_total counter",
        f"desk_power_guardian_offs_total {event_counts['OFF_TRIGGERED'] + event_counts['HARD_CUTOFF_USED']}",
        "# HELP desk_power_guardian_override_active Whether today's override is active.",
        "# TYPE desk_power_guardian_override_active gauge",
        f"desk_power_guardian_override_active {1 if decision['override_today'] else 0}",
        "# HELP desk_power_guardian_postponed_pending Whether a postponed evaluation is currently scheduled.",
        "# TYPE desk_power_guardian_postponed_pending gauge",
        f"desk_power_guardian_postponed_pending {1 if decision['schedule']['next_postponed_evaluation'] else 0}",
        "# HELP desk_power_guardian_latest_power_watts Latest observed telemetry power in watts.",
        "# TYPE desk_power_guardian_latest_power_watts gauge",
        f"desk_power_guardian_latest_power_watts {decision['activity']['power_watts'] if decision['activity']['power_watts'] is not None else 'NaN'}",
        "# HELP desk_power_guardian_activity_state Current activity state encoded as a labeled gauge.",
        "# TYPE desk_power_guardian_activity_state gauge",
        f"desk_power_guardian_activity_state{{state=\"{decision['activity']['state']}\"}} 1",
    ]
    return "\n".join(metrics) + "\n"