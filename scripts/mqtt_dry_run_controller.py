from __future__ import annotations

import argparse
import sys
import time
from collections import deque
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from desk_power_guardian.activity import ActivityClassifier
from desk_power_guardian.config import load_settings
from desk_power_guardian.script_support import build_mqtt_client, evaluate_simulated_decision
from desk_power_guardian.telemetry import TelemetrySample, parse_telemetry_message


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Simulate the auto-off controller without publishing MQTT commands.")
    parser.add_argument("--duration-seconds", type=int, default=1800, help="How long to run the simulation.")
    parser.add_argument("--evaluate-interval-seconds", type=int, default=60, help="How often to evaluate the current decision.")
    parser.add_argument("--override-today", action="store_true", help="Simulate an active one-time override for the current day.")
    parser.add_argument("--topic", help="Override the telemetry topic wildcard.")
    parser.add_argument("--show-command", action="store_true", help="Print the command topic and payload for OFF decisions.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = load_settings()
    classifier = ActivityClassifier(settings)
    samples: deque[TelemetrySample] = deque(maxlen=settings.telemetry_window_size)
    topic = args.topic or settings.telemetry_wildcard_topic
    client = build_mqtt_client(settings, client_id_prefix="dry-run-controller")
    last_signature: tuple[str, str] | None = None

    def now_provider() -> datetime:
        return datetime.now(settings.timezone)

    def render_decision() -> None:
        nonlocal last_signature
        decision = evaluate_simulated_decision(
            settings=settings,
            classifier=classifier,
            samples=list(samples),
            now=now_provider(),
            override_today=args.override_today,
        )
        signature = (decision.outcome, decision.reason)
        if signature == last_signature and decision.outcome == "BEFORE_AUTO_OFF":
            return
        last_signature = signature
        print(f"{now_provider().isoformat()} outcome={decision.outcome} reason={decision.reason}")
        quiet_window = decision.details.get("quiet_window")
        if quiet_window:
            print(
                "  quiet_window="
                f"off_allowed={quiet_window['off_allowed']} "
                f"reason={quiet_window['reason']} "
                f"quiet_for_seconds={quiet_window['quiet_for_seconds']:.1f} "
                f"latest_state={quiet_window['latest_state']}"
            )
        if args.show_command and "command_topic" in decision.details:
            print(
                "  would_publish "
                f"topic={decision.details['command_topic']} payload={decision.details['command_payload']}"
            )

    def on_connect(client_obj, userdata, flags, rc):
        if rc != 0:
            print(f"connect failed rc={rc}", file=sys.stderr)
            client_obj.disconnect()
            return
        client_obj.subscribe(topic, qos=0)
        print(f"simulating topic={topic} duration={args.duration_seconds}s interval={args.evaluate_interval_seconds}s")

    def on_message(client_obj, userdata, msg):
        sample = parse_telemetry_message(msg.topic, msg.payload, settings, now_provider)
        if sample is None:
            return
        samples.append(sample)
        print(f"sample time={sample.created_at.isoformat()} power={sample.power_watts:.2f}W topic={sample.topic}")

    client.on_connect = on_connect
    client.on_message = on_message
    try:
        client.connect(settings.mqtt_host, settings.mqtt_port, keepalive=30)
    except Exception as exc:
        print(f"failed to connect to MQTT broker {settings.mqtt_host}:{settings.mqtt_port}: {exc}", file=sys.stderr)
        return 1
    client.loop_start()

    try:
        end_time = time.monotonic() + args.duration_seconds
        next_evaluation = time.monotonic()
        while time.monotonic() < end_time:
            if time.monotonic() >= next_evaluation:
                render_decision()
                next_evaluation = time.monotonic() + args.evaluate_interval_seconds
            time.sleep(0.2)
    finally:
        if client.is_connected():
            client.disconnect()
        client.loop_stop()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())