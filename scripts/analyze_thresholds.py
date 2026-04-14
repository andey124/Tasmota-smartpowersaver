from __future__ import annotations

import argparse
import csv
import math
from datetime import datetime
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze recorded power telemetry and propose thresholds.")
    parser.add_argument("--input", required=True, help="Input CSV path with timestamp,power_watts.")
    parser.add_argument("--output", default="artifacts/threshold_report.md", help="Markdown report output path.")
    parser.add_argument("--histogram-buckets", type=int, default=10, help="Number of histogram buckets.")
    return parser.parse_args()


def quantile(values: list[float], q: float) -> float:
    if not values:
        raise ValueError("quantile requires at least one value")
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * q
    lower_index = math.floor(position)
    upper_index = math.ceil(position)
    if lower_index == upper_index:
        return values[lower_index]
    lower_value = values[lower_index]
    upper_value = values[upper_index]
    return lower_value + (upper_value - lower_value) * (position - lower_index)


def histogram(values: list[float], bucket_count: int) -> list[tuple[float, float, int]]:
    if not values:
        return []
    low = min(values)
    high = max(values)
    if low == high:
        return [(low, high, len(values))]
    bucket_width = (high - low) / bucket_count
    buckets = [0 for _ in range(bucket_count)]
    for value in values:
        index = min(int((value - low) / bucket_width), bucket_count - 1)
        buckets[index] += 1
    ranges: list[tuple[float, float, int]] = []
    for index, count in enumerate(buckets):
        start = low + index * bucket_width
        end = high if index == bucket_count - 1 else start + bucket_width
        ranges.append((start, end, count))
    return ranges


def round_threshold(value: float) -> float:
    return round(value / 5.0) * 5.0


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    timestamps: list[datetime] = []
    values: list[float] = []
    with input_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            timestamps.append(datetime.fromisoformat(row["timestamp"]))
            values.append(float(row["power_watts"]))

    if not values:
        raise SystemExit("input CSV did not contain any samples")

    ordered = sorted(values)
    q05 = quantile(ordered, 0.05)
    q25 = quantile(ordered, 0.25)
    q50 = quantile(ordered, 0.50)
    q75 = quantile(ordered, 0.75)
    q95 = quantile(ordered, 0.95)
    idle_threshold = round_threshold(q25)
    active_threshold = max(idle_threshold + 5.0, round_threshold(q75))
    spread = q75 - q25
    if len(values) >= 100 and spread >= 20.0:
        confidence = "high"
    elif len(values) >= 40 and spread >= 10.0:
        confidence = "medium"
    else:
        confidence = "low"

    report_lines = [
        "# Threshold Analysis Report",
        "",
        f"Generated from `{input_path}`.",
        "",
        "## Summary",
        "",
        f"- Samples: {len(values)}",
        f"- Time range: {min(timestamps).isoformat()} to {max(timestamps).isoformat()}",
        f"- Minimum watts: {min(values):.2f}",
        f"- Maximum watts: {max(values):.2f}",
        f"- Median watts: {q50:.2f}",
        "",
        "## Quantiles",
        "",
        "| Quantile | Watts |",
        "| --- | ---: |",
        f"| 5% | {q05:.2f} |",
        f"| 25% | {q25:.2f} |",
        f"| 50% | {q50:.2f} |",
        f"| 75% | {q75:.2f} |",
        f"| 95% | {q95:.2f} |",
        "",
        "## Suggested Thresholds",
        "",
        f"- Recommended `IDLE_WATTS_THRESHOLD`: {idle_threshold:.0f}",
        f"- Recommended `ACTIVE_WATTS_THRESHOLD`: {active_threshold:.0f}",
        f"- Confidence: {confidence}",
        "",
        "## Histogram",
        "",
        "| Range (W) | Count |",
        "| --- | ---: |",
    ]
    for bucket_start, bucket_end, count in histogram(ordered, args.histogram_buckets):
        report_lines.append(f"| {bucket_start:.2f} - {bucket_end:.2f} | {count} |")

    report_lines.extend(
        [
            "",
            "## Notes",
            "",
            "- `IDLE_WATTS_THRESHOLD` is anchored near the lower quartile to stay conservative about idle detection.",
            "- `ACTIVE_WATTS_THRESHOLD` is anchored near the upper quartile to require a clearer activity signal.",
            "- If the histogram shows a single broad cluster instead of two bands, collect more recordings across both active and idle sessions.",
        ]
    )

    output_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    print(f"wrote report to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())