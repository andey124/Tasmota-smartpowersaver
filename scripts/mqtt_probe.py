from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from desk_power_guardian.config import load_settings
from desk_power_guardian.script_support import build_mqtt_client, summarize_probe_message


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe Tasmota MQTT telemetry and status topics.")
    parser.add_argument("--timeout-seconds", type=int, default=30, help="Exit after this many seconds if no telemetry arrives.")
    parser.add_argument("--message-limit", type=int, default=20, help="Stop after printing this many messages.")
    parser.add_argument("--topic-base", help="Override Tasmota base topic from the environment.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = load_settings()
    topic_base = args.topic_base or settings.tasmota_base_topic
    telemetry_topic = f"{settings.telemetry_topic_prefix}/{topic_base}/#"
    status_topic = f"{settings.tasmota_status_prefix}/{topic_base}/#"

    seen_telemetry = False
    seen_messages = 0
    exit_code = 0
    client = build_mqtt_client(settings, client_id_prefix="mqtt-probe")

    def now_provider() -> datetime:
        return datetime.now(settings.timezone)

    def on_connect(client_obj, userdata, flags, rc):
        if rc != 0:
            print(f"connect failed rc={rc}", file=sys.stderr)
            client_obj.disconnect()
            return
        client_obj.subscribe([(telemetry_topic, 0), (status_topic, 0)])
        print(f"subscribed telemetry={telemetry_topic} status={status_topic}")

    def on_message(client_obj, userdata, msg):
        nonlocal seen_telemetry, seen_messages
        is_telemetry, summary = summarize_probe_message(msg.topic, msg.payload, settings, now_provider)
        if is_telemetry:
            seen_telemetry = True
        seen_messages += 1
        print(summary)
        if seen_messages >= args.message_limit:
            client_obj.disconnect()

    def on_disconnect(client_obj, userdata, rc):
        if rc != 0 and not seen_telemetry:
            print(f"disconnected rc={rc}", file=sys.stderr)

    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect
    try:
        client.connect(settings.mqtt_host, settings.mqtt_port, keepalive=30)
    except Exception as exc:
        print(f"failed to connect to MQTT broker {settings.mqtt_host}:{settings.mqtt_port}: {exc}", file=sys.stderr)
        return 1
    client.loop_start()

    try:
        deadline = time.monotonic() + args.timeout_seconds
        while time.monotonic() < deadline:
            if seen_messages >= args.message_limit:
                break
            time.sleep(0.1)
        if not seen_telemetry:
            print(f"no telemetry received within {args.timeout_seconds}s", file=sys.stderr)
            exit_code = 1
    finally:
        if client.is_connected():
            client.disconnect()
        client.loop_stop()

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())