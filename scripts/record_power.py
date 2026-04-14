from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from desk_power_guardian.config import load_settings
from desk_power_guardian.script_support import build_mqtt_client
from desk_power_guardian.telemetry import parse_telemetry_message


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record Tasmota power telemetry to CSV.")
    parser.add_argument("--duration-seconds", type=int, default=1800, help="How long to record for.")
    parser.add_argument("--output", required=True, help="CSV output path.")
    parser.add_argument("--topic", help="Override the telemetry topic wildcard.")
    parser.add_argument("--append", action="store_true", help="Append to an existing CSV file.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = load_settings()
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    topic = args.topic or settings.telemetry_wildcard_topic
    write_header = not args.append or not output_path.exists()
    samples_written = 0

    client = build_mqtt_client(settings, client_id_prefix="record-power")

    def now_provider() -> datetime:
        return datetime.now(settings.timezone)

    with output_path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        if write_header:
            writer.writerow(["timestamp", "power_watts"])

        def on_connect(client_obj, userdata, flags, rc):
            if rc != 0:
                print(f"connect failed rc={rc}", file=sys.stderr)
                client_obj.disconnect()
                return
            client_obj.subscribe(topic, qos=0)
            print(f"recording topic={topic} output={output_path}")

        def on_message(client_obj, userdata, msg):
            nonlocal samples_written
            sample = parse_telemetry_message(msg.topic, msg.payload, settings, now_provider)
            if sample is None:
                return
            writer.writerow([sample.created_at.isoformat(), f"{sample.power_watts:.3f}"])
            handle.flush()
            samples_written += 1
            print(f"sample {samples_written}: {sample.created_at.isoformat()} {sample.power_watts:.2f}W")

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
            while time.monotonic() < end_time and client.is_connected():
                time.sleep(0.2)
        finally:
            if client.is_connected():
                client.disconnect()
            client.loop_stop()

    print(f"wrote {samples_written} samples to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())