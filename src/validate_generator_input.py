"""Validate stations.csv against the actual teacher generator input contract."""

from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_COLUMNS = ["station_id", "name", "lat", "lon", "site_type", "connectors", "max_kw"]


def validate() -> dict:
    path = ROOT / "data/input/stations.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != EXPECTED_COLUMNS:
            raise AssertionError(f"Unexpected columns: {reader.fieldnames}")
        rows = list(reader)

    ids = [row["station_id"] for row in rows]
    if not rows or len(ids) != len(set(ids)) or any(not value for value in ids):
        raise AssertionError("station_id must be nonempty and unique")
    for row in rows:
        if not row["name"].strip():
            raise AssertionError(f"Missing name: {row['station_id']}")
        lat, lon = float(row["lat"]), float(row["lon"])
        if not (-44 <= lat <= -10 and 110 <= lon <= 160):
            raise AssertionError(f"Invalid NSW/Australia coordinate: {row['station_id']}")
        if row["site_type"] not in {"urban", "regional"}:
            raise AssertionError(f"Invalid site_type: {row['station_id']}")
        if int(row["connectors"]) <= 0 or float(row["max_kw"]) <= 0:
            raise AssertionError(f"Non-positive connector/power value: {row['station_id']}")

    with (ROOT / "data/processed/generator_station_mapping.csv").open(encoding="utf-8", newline="") as handle:
        mapping = list(csv.DictReader(handle))
    if {row["generator_station_id"] for row in mapping} != set(ids):
        raise AssertionError("Generator station mapping does not cover stations.csv exactly")

    result = {
        "result": "PASS",
        "rows": len(rows),
        "columns": EXPECTED_COLUMNS,
        "urban_rows": sum(row["site_type"] == "urban" for row in rows),
        "regional_rows": sum(row["site_type"] == "regional" for row in rows),
        "connectors": sum(int(row["connectors"]) for row in rows),
        "one_day_hourly_price_rows": len(rows) * 24,
        "generator_execution": "NOT_RUN",
    }
    (ROOT / "docs/generator_input_validation.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    return result


if __name__ == "__main__":
    print(json.dumps(validate(), indent=2))
