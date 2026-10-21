"""Validate the unmodified teacher generator's Task 1 outputs (standard library)."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
START = datetime(2026, 9, 15)
END = START + timedelta(days=1)
AEMO_NAME = "PRICE_AND_DEMAND_202609_NSW1.csv"
AEMO_URL = "https://www.aemo.com.au/aemo/data/nem/priceanddemand/" + AEMO_NAME
OUTPUT_NAMES = ("stations.csv", "prices_hourly.csv", "sessions.csv", "session_metering.csv")
# Session energy is rounded to 0.01 kWh; meters to 0.001 kWh.
ENERGY_TOLERANCE = 0.0055 + 1e-9


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def number(value: str, label: str) -> float:
    parsed = float(value)
    require(math.isfinite(parsed), f"Non-finite {label}")
    return parsed


def timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    require(parsed.tzinfo is None, "Raw generator timestamps must remain naive NEM clock time")
    return parsed


def unique(data: list[dict], key: str, label: str) -> dict[str, dict]:
    result = {row[key]: row for row in data}
    require(bool(data) and "" not in result and len(result) == len(data), f"Duplicate/empty {label}")
    return result


def validate_aemo(path: Path) -> tuple[dict, dict[datetime, float]]:
    selected = {}
    for row in rows(path):
        end_time = datetime.strptime(row["SETTLEMENTDATE"], "%Y/%m/%d %H:%M:%S")
        if not START < end_time <= END:
            continue
        require(row["REGION"] == "NSW1", "Unexpected AEMO region")
        require(row["PERIODTYPE"] == "TRADE", "Unexpected AEMO period type")
        require(end_time not in selected, "Duplicate AEMO interval")
        selected[end_time] = number(row["RRP"], "AEMO RRP") / 1000
    expected = {START + timedelta(minutes=5 * i) for i in range(1, 289)}
    require(set(selected) == expected, f"Incomplete AEMO day: {len(selected)}/288 intervals")
    buckets = defaultdict(list)
    for end_time, price in sorted(selected.items()):
        hour = (end_time - timedelta(minutes=5)).replace(minute=0, second=0)
        buckets[hour].append(price)
    hourly = {hour: sum(values) / len(values) for hour, values in buckets.items()}
    return {
        "result": "PASS", "source_url": AEMO_URL, "sha256": digest(path),
        "region": "NSW1", "date": START.date().isoformat(), "intervals": len(selected),
        "first_period_end": min(selected).isoformat(), "last_period_end": max(selected).isoformat(),
        "hours": len(hourly), "time_basis": "NEM market time (AEST, UTC+10, no daylight saving)",
    }, hourly


def validate(root: Path = ROOT, output: Path | None = None) -> dict:
    output = output or root / "data/generated"
    aemo, wholesale = validate_aemo(output / "aemo_cache" / AEMO_NAME)
    inputs = unique(rows(root / "data/input/stations.csv"), "station_id", "input station ID")
    mapping = unique(rows(root / "data/processed/generator_station_mapping.csv"),
                     "generator_station_id", "mapping ID")
    physical = unique(rows(root / "data/processed/stations_prepared.csv"), "station_id", "physical station ID")
    chargers = unique(rows(root / "data/processed/chargers_prepared.csv"), "charger_id", "charger ID")
    require(set(inputs) == set(mapping), "Mapping does not cover generator input exactly")
    for sid, row in mapping.items():
        require(row["charger_id"] == sid and sid in chargers, f"Incorrect charger mapping: {sid}")
        require(row["physical_station_id"] in physical and
                chargers[sid]["station_id"] == row["physical_station_id"], f"Incorrect physical station mapping: {sid}")

    stations = unique(rows(output / "stations.csv"), "station_id", "generated station ID")
    require(set(stations) == set(inputs), "Generated stations differ from input IDs")
    for sid, row in stations.items():
        original = inputs[sid]
        for key in ("name", "site_type"):
            require(row[key] == original[key], f"Input metadata changed: {sid}/{key}")
        for key in ("lat", "lon", "connectors", "max_kw"):
            require(number(row[key], key) == number(original[key], key), f"Input numeric metadata changed: {sid}/{key}")
        require(number(row["base_price"], "base price") > 0, "Non-positive base price")

    prices = {}
    hourly_mean = sum(wholesale.values()) / len(wholesale)
    for row in rows(output / "prices_hourly.csv"):
        sid, time = row["station_id"], timestamp(row["ts"])
        require(sid in inputs and time in wholesale, "Orphan station or unexpected price timestamp")
        key = (sid, time)
        require(key not in prices, "Duplicate hourly price")
        actual = number(row["price_per_kwh"], "retail price")
        require(abs(number(row["wholesale_per_kwh"], "wholesale price") - round(wholesale[time], 4)) < 1e-9,
                "Wholesale price differs from complete AEMO intervals")
        expected = float(stations[sid]["base_price"]) + wholesale[time] - hourly_mean
        expected += 0.10 if 16 <= time.hour < 21 else 0
        expected = round(min(max(expected, 0.20), 1.20), 2)
        require(abs(actual - expected) < 1e-9, "Retail price differs from generator dynamic-price formula")
        prices[key] = actual
    require(set(prices) == {(sid, hour) for sid in inputs for hour in wholesale}, "Missing hourly prices")

    sessions = unique(rows(output / "sessions.csv"), "session_id", "session ID")
    intervals = defaultdict(list)
    session_times = {}
    for session_id, row in sessions.items():
        sid = row["station_id"]
        require(sid in inputs, "Orphan session station")
        connector = int(row["connector_id"])
        require(1 <= connector <= int(inputs[sid]["connectors"]), "Connector outside input range")
        start, charge_end, end = (timestamp(row[key]) for key in ("start_ts", "charge_end_ts", "end_ts"))
        require(START <= start < END and start < charge_end <= end, "Invalid session time order/window")
        minutes = (charge_end - start).total_seconds() / 60
        require(abs(number(row["charge_minutes"], "duration") - minutes) < 1e-9, "Session duration mismatch")
        require(number(row["energy_kwh"], "session energy") > 0, "Non-positive session energy")
        for key in ("avg_kw", "peak_kw", "cost_aud"):
            require(number(row[key], key) >= 0, f"Negative {key}")
        require(row["site_type"] == inputs[sid]["site_type"], "Session site type mismatch")
        hour = start.replace(minute=0, second=0, microsecond=0)
        require(number(row["price_per_kwh"], "session price") == prices[sid, hour], "Session start tariff mismatch")
        # Both final energy and cost are rounded by the teacher script.
        require(abs(float(row["cost_aud"]) - float(row["energy_kwh"]) * prices[sid, hour]) <=
                0.005 + 0.005 * prices[sid, hour] + 1e-9, "Session cost mismatch")
        intervals[sid, connector].append((start, end))
        session_times[session_id] = (start, charge_end, end)
    for values in intervals.values():
        ordered = sorted(values)
        require(all(a[1] <= b[0] for a, b in zip(ordered, ordered[1:])), "Overlapping connector sessions")

    previous = {}
    meter_counts = defaultdict(int)
    previous_global = None
    with (output / "session_metering.csv").open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            session_id = row["session_id"]
            require(session_id in sessions, "Orphan meter session")
            session = sessions[session_id]
            require(row["type"] == "meter", "Unexpected meter event type")
            require(row["station_id"] == session["station_id"] and
                    row["connector_id"] == session["connector_id"], "Meter identity mismatch")
            time = timestamp(row["ts"])
            energy = number(row["energy_kwh"], "meter energy")
            soc = number(row["soc_pct"], "state of charge")
            start, charge_end, _ = session_times[session_id]
            require(start < time <= charge_end, "Meter outside charging interval")
            last_time, last_energy, last_soc = previous.get(session_id, (start, 0.0, 0.0))
            require(time - last_time == timedelta(minutes=1), "Missing, duplicate or unordered minute meter")
            require(energy >= last_energy and 0 <= soc <= 100 and soc >= last_soc, "Decreasing meter energy or SoC")
            require(energy <= float(session["energy_kwh"]) + ENERGY_TOLERANCE, "Meter exceeds final session energy")
            for key in ("voltage_v", "current_a", "power_kw"):
                require(number(row[key], key) > 0, f"Non-positive meter {key}")
            order = (time, session_id)
            require(previous_global is None or order >= previous_global, "Meter file is not globally time ordered")
            previous_global = order
            previous[session_id] = (time, energy, soc)
            meter_counts[session_id] += 1
    require(set(previous) == set(sessions), "Session without meter readings")
    for sid, row in sessions.items():
        require(previous[sid][0] == session_times[sid][1], "Missing final meter reading")
        require(abs(previous[sid][1] - float(row["energy_kwh"])) <= ENERGY_TOLERANCE, "Final meter energy mismatch")
        require(meter_counts[sid] == int(float(row["charge_minutes"])), "Meter count differs from charging minutes")

    return {
        "result": "PASS", "aemo": aemo,
        "generator_configurations": len(inputs), "physical_stations": len({r["physical_station_id"] for r in mapping.values()}),
        "connectors": sum(int(r["connectors"]) for r in inputs.values()),
        "hourly_prices": len(prices), "charging_sessions": len(sessions), "meter_events": sum(meter_counts.values()),
        "sessions_by_site_type": {kind: sum(r["site_type"] == kind for r in sessions.values()) for kind in ("urban", "regional")},
        "sessions_ending_after_generation_day": sum(times[2] > END for times in session_times.values()),
        "last_session_end": max(times[2] for times in session_times.values()).isoformat(),
        "price_min": min(prices.values()), "price_max": max(prices.values()),
        "session_count_note": "4,266 is a nominal rate calculation, not a fixed assertion; actual stochastic count is reported unchanged.",
        "meter_energy_rounding_tolerance_kwh": 0.0055,
        "checks": ["complete_aemo_day", "input_and_metadata_mapping", "generated_station_metadata",
                   "hourly_price_coverage_and_uniqueness", "aemo_and_dynamic_price_formula", "session_ids_and_foreign_keys",
                   "connector_range_and_nonoverlap", "session_timing_energy_cost", "meter_session_identity",
                   "complete_ordered_minute_meters", "monotone_energy_and_soc", "final_meter_energy_and_duration"],
        "outputs": {name: {"bytes": (output / name).stat().st_size, "sha256": digest(output / name)} for name in OUTPUT_NAMES},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/generated")
    parser.add_argument("--report", type=Path, default=ROOT / "docs/task1_validation.json")
    args = parser.parse_args()
    try:
        result = validate(ROOT, args.output_dir)
    except (ValueError, KeyError, OSError) as exc:
        result = {"result": "FAIL", "error": str(exc)}
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        raise
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
