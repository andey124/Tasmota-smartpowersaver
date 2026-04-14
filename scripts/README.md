# Scripts

Phase 2a adds operator scripts for MQTT validation, dry-run simulation, telemetry capture, and threshold analysis.

## Requirements

Run these from the repository root after installing dependencies:

```bash
pip install -r requirements.txt
```

When launched from the repository root, the scripts automatically read local values from `.env` unless the same variables are already exported in the shell.

If you prefer not to install locally, you can run them in the existing project image:

```bash
docker run --rm -v "$PWD:/work" -w /work tasmota-smartpowersaver-desk-power-guardian \
  sh -lc 'PYTHONPATH=/work/src python scripts/mqtt_probe.py --help'
```

## MQTT Probe

Confirm broker connectivity and topic wiring without sending commands:

```bash
PYTHONPATH=src python scripts/mqtt_probe.py --timeout-seconds 30 --message-limit 20
```

The script subscribes to both `tele/<topic>/#` and `stat/<topic>/#` and exits with a non-zero status if no telemetry arrives before the timeout.

## Dry-Run Controller

Simulate the evening decision loop without publishing `POWER OFF`:

```bash
PYTHONPATH=src python scripts/mqtt_dry_run_controller.py \
  --duration-seconds 1800 \
  --evaluate-interval-seconds 60 \
  --show-command
```

Possible outcomes include `BEFORE_AUTO_OFF`, `OFF_ALLOWED`, `POSTPONED_ACTIVE`, `POSTPONED_WAITING_IDLE`, `OVERRIDE_ACTIVE`, and `HARD_CUTOFF_USED`.

## Record Power

Record raw telemetry to CSV for threshold tuning:

```bash
PYTHONPATH=src python scripts/record_power.py \
  --duration-seconds 3600 \
  --output artifacts/power_evening.csv
```

The output file contains `timestamp,power_watts` rows.

## Analyze Thresholds

Generate a markdown recommendation report from a recorded CSV:

```bash
python scripts/analyze_thresholds.py \
  --input artifacts/power_evening.csv \
  --output artifacts/threshold_report.md
```

The report includes quantiles, a histogram, suggested idle/active thresholds, and confidence notes.

## Anonymous vs Authenticated MQTT

By default the scripts follow the main service settings:

- `MQTT_ALLOW_ANONYMOUS=true` means no username/password will be sent.
- If `MQTT_ALLOW_ANONYMOUS=false`, the scripts use `MQTT_USERNAME` and `MQTT_PASSWORD` from the environment.

## Recommended Operator Flow

1. Run `mqtt_probe.py` to confirm topic wiring.
2. Run `mqtt_dry_run_controller.py` during a real evening session.
3. Run `record_power.py` to capture at least one clearly idle period and one clearly active period.
4. Run `analyze_thresholds.py` to produce threshold recommendations.