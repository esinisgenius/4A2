"""Prepare ordered MQTT payloads from Task 1 CSVs; no broker connection is made.

Naive generator times use fixed NEM/AEST (UTC+10). Optional replay windows
are half-open and expressed on that same clock. See docs/task2_events.md.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NEM = timezone(timedelta(hours=10))
PRIORITY = {"price_update": 0, "meter": 1, "session_end": 2, "session_start": 3}
SCHEMA_VERSION = "1.0"
SOURCE_FILES = {
    "stations": "data/generated/stations.csv",
    "mapping": "data/processed/generator_station_mapping.csv",
    "prices": "data/generated/prices_hourly.csv",
    "sessions": "data/generated/sessions.csv",
    "meters": "data/generated/session_metering.csv",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def market_time(value: str) -> datetime:
    """Read an unambiguous, offset-free timestamp on the generator's clock."""
    parsed = datetime.fromisoformat(value)
    require(parsed.tzinfo is None, f"Expected offset-free NEM time: {value}")
    require("T" in value or " " in value, f"Include the time as well as the date: {value}")
    require(parsed.microsecond == 0, f"Sub-second source timestamps are unsupported: {value}")
    return parsed


def utc_string(value: datetime) -> str:
    return value.replace(tzinfo=NEM).astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def number(value: str, label: str, minimum: Decimal = Decimal(0)) -> Decimal:
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid {label}: {value!r}") from exc
    require(result.is_finite() and result >= minimum, f"Invalid {label}: {value!r}")
    return result


def read_csv(path: Path, required: set[str]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        require(required <= set(reader.fieldnames or []), f"Missing columns in {path.name}: {sorted(required-set(reader.fieldnames or []))}")
        result = list(reader)
    require(bool(result), f"Empty input: {path}")
    require(all(None not in row and all(row[k] is not None for k in required) for row in result), f"Malformed CSV: {path}")
    return result


def unique(rows: list[dict], key: str, label: str) -> dict[str, dict]:
    indexed = {row[key]: row for row in rows}
    require(len(indexed) == len(rows) and all(indexed), f"Duplicate/empty {label}")
    return indexed


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def event_key(event: dict) -> tuple:
    return event["event_time"], PRIORITY[event["event_type"]], event["event_id"]


def prepare(root: Path = ROOT, start: datetime | None = None, end: datetime | None = None) -> tuple[list[dict], dict]:
    """Return payloads and a manifest. This function does not write files."""
    require((start is None) == (end is None), "Supply both --start and --end, or neither")
    if start is not None:
        require(start.tzinfo is None and end.tzinfo is None and start < end, "Window must have increasing, offset-free NEM times")
        require(start.microsecond == end.microsecond == 0, "Window timestamps must use whole seconds")
    paths = {key: root / name for key, name in SOURCE_FILES.items()}
    stations = unique(read_csv(paths["stations"], {"station_id", "connectors"}), "station_id", "generated station ID")
    mapping = unique(read_csv(paths["mapping"], {"generator_station_id", "physical_station_id", "charger_id"}), "generator_station_id", "mapping ID")
    require(stations.keys() == mapping.keys(), "Mapping must cover generated configurations exactly")
    for cid, row in mapping.items():
        require(row["charger_id"] == cid and bool(row["physical_station_id"]), f"Invalid charger/site mapping: {cid}")
    capacities = {}
    for cid, row in stations.items():
        require(row["connectors"].isdigit() and int(row["connectors"]) > 0, f"Invalid connector count: {cid}")
        capacities[cid] = int(row["connectors"])

    prices = read_csv(paths["prices"], {"station_id", "ts", "price_per_kwh"})
    sessions = unique(read_csv(paths["sessions"], {"session_id", "station_id", "connector_id", "start_ts", "charge_end_ts", "end_ts", "vehicle_model", "site_type", "price_per_kwh", "energy_kwh", "charge_minutes", "avg_kw", "peak_kw", "cost_aud"}), "session_id", "session ID")
    meters = read_csv(paths["meters"], {"type", "station_id", "connector_id", "session_id", "ts", "voltage_v", "current_a", "power_kw", "energy_kwh", "soc_pct"})
    # Logical identities do not depend on CSV row ordering or CRLF vs LF.
    identity = {
        "stations": sorted(stations.values(), key=lambda r: r["station_id"]),
        "mapping": sorted(mapping.values(), key=lambda r: r["generator_station_id"]),
        "prices": sorted(prices, key=lambda r: (r["station_id"], r["ts"])),
        "sessions": sorted(sessions.values(), key=lambda r: r["session_id"]),
        "meters": sorted(meters, key=lambda r: (r["session_id"], r["ts"])),
    }
    dataset_id = "ds_" + hashlib.sha256(canonical(identity)).hexdigest()
    del identity
    provenance = {name: {"path": SOURCE_FILES[name], "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for name, path in paths.items()}

    def event(kind: str, cid: str, time: datetime, fields: dict) -> dict:
        payload = {"schema_version": SCHEMA_VERSION, "dataset_id": dataset_id,
                   "event_type": kind, "event_time": utc_string(time),
                   "station_id": mapping[cid]["physical_station_id"], "charger_id": cid, **fields}
        payload["event_id"] = "evt_" + hashlib.sha256(canonical(payload)).hexdigest()
        return payload

    price_rows = defaultdict(list)
    price_keys = set()
    for row in prices:
        cid, time = row["station_id"], market_time(row["ts"])
        require(cid in mapping, f"Unknown price charger: {cid}")
        require(time.minute == time.second == 0, f"Price is not hourly: {row['ts']}")
        require((cid, time) not in price_keys, f"Duplicate price: {cid}/{time}")
        price_keys.add((cid, time))
        price_rows[cid].append((time, number(row["price_per_kwh"], "price")))
    require(price_rows.keys() == mapping.keys(), "Missing configuration price history")
    price_changes = {}
    source_min, source_end = min(t for _, t in price_keys), max(t for _, t in price_keys) + timedelta(hours=1)
    for cid, values in price_rows.items():
        ordered = sorted(values)
        require(ordered[0][0] == source_min and ordered[-1][0] + timedelta(hours=1) == source_end,
                f"Inconsistent price coverage: {cid}")
        require(all(b[0] - a[0] == timedelta(hours=1) for a, b in zip(ordered, ordered[1:])), f"Missing hourly price: {cid}")
        previous = None
        changes = []
        for time, price in ordered:
            if price != previous:
                changes.append((time, event("price_update", cid, time, {
                    "price_per_kwh": float(price), "currency": "AUD", "price_unit": "AUD/kWh"})))
            previous = price
        price_changes[cid] = changes
    if start is not None:
        require(source_min <= start < end <= source_end, "Replay window must lie inside the hourly-price coverage; full mode includes cross-day session tails")

    bounds = {}
    groups = defaultdict(list)
    for sid, row in sessions.items():
        cid, connector = row["station_id"], row["connector_id"]
        require(cid in mapping, f"Unknown session charger: {cid}")
        require(connector.isdigit() and str(int(connector)) == connector and 1 <= int(connector) <= capacities[cid], f"Invalid connector: {sid}")
        a, b, c = (market_time(row[key]) for key in ("start_ts", "charge_end_ts", "end_ts"))
        require(source_min <= a < source_end and a < b <= c, f"Invalid session times: {sid}")
        bounds[sid] = (a, b, c)
        groups[cid, connector].append((a, c, sid))
        for key in ("price_per_kwh", "energy_kwh", "charge_minutes", "avg_kw", "peak_kw", "cost_aud"):
            number(row[key], key)
        hour = a.replace(minute=0, second=0)
        tariff = next(p for t, p in price_rows[cid] if t == hour)
        require(number(row["price_per_kwh"], "session price") == tariff, f"Session start tariff mismatch: {sid}")
    for values in groups.values():
        ordered = sorted(values)
        require(all(a[1] <= b[0] for a, b in zip(ordered, ordered[1:])), "Overlapping sessions on the same connector")

    selected = {sid for sid, (a, _, c) in bounds.items() if start is None or (a < end and c >= start)}
    warmup_start = min([start, *(bounds[sid][0] for sid in selected)]) if start is not None else source_min
    output = []
    for cid, changes in price_changes.items():
        if start is None:
            output.extend(e for _, e in changes)
        else:
            baseline = [e for t, e in changes if t <= warmup_start]
            require(bool(baseline), f"No initial price for {cid}")
            output.append(baseline[-1])
            output.extend(e for t, e in changes if warmup_start < t < end)

    for sid in sorted(selected):
        row = sessions[sid]
        a, b, c = bounds[sid]
        common = {"session_id": sid, "connector_id": row["connector_id"]}
        output.append(event("session_start", row["station_id"], a, {
            **common, "vehicle_model": row["vehicle_model"], "site_type": row["site_type"],
            "price_per_kwh": float(number(row["price_per_kwh"], "price")), "currency": "AUD"}))
        if end is None or c < end:
            output.append(event("session_end", row["station_id"], c, {
                **common, "charge_end_time": utc_string(b), "currency": "AUD",
                **{key: float(number(row[key], key)) for key in ("energy_kwh", "charge_minutes", "avg_kw", "peak_kw", "price_per_kwh", "cost_aud")}}))

    meter_keys = set()
    meter_groups = defaultdict(list)
    for row in meters:
        sid = row["session_id"]
        require(sid in sessions, f"Orphan meter session: {sid}")
        session = sessions[sid]
        require(row["type"] == "meter", f"Invalid meter type: {sid}")
        require(row["station_id"] == session["station_id"] and row["connector_id"] == session["connector_id"], f"Meter identity mismatch: {sid}")
        time = market_time(row["ts"])
        require(bounds[sid][0] < time <= bounds[sid][1], f"Meter outside charge interval: {sid}")
        require((sid, time) not in meter_keys, f"Duplicate meter: {sid}/{time}")
        meter_keys.add((sid, time))
        fields = {key: float(number(row[key], key)) for key in ("voltage_v", "current_a", "power_kw", "energy_kwh", "soc_pct")}
        require(fields["soc_pct"] <= 100, f"Invalid SoC: {sid}")
        meter_groups[sid].append((time, fields["energy_kwh"], fields["soc_pct"]))
        if sid in selected and (end is None or time < end):
            output.append(event("meter", row["station_id"], time, {
                "session_id": sid, "connector_id": row["connector_id"], **fields}))
    require(meter_groups.keys() == sessions.keys(), "Session without meter readings")
    for sid, values in meter_groups.items():
        ordered = sorted(values)
        previous = (bounds[sid][0], 0.0, 0.0)
        for current in ordered:
            require(current[0] - previous[0] == timedelta(minutes=1), f"Missing minute meter: {sid}")
            require(current[1] >= previous[1] and current[2] >= previous[2], f"Decreasing energy/SoC: {sid}")
            previous = current
        require(previous[0] == bounds[sid][1], f"Missing final meter: {sid}")
        require(abs(previous[1] - float(sessions[sid]["energy_kwh"])) <= 0.0055 + 1e-9, f"Final meter energy mismatch: {sid}")

    output.sort(key=event_key)
    for index, payload in enumerate(output, 1):
        payload["sequence"] = index
    replay_checks = validate_stream(output)
    start_utc = utc_string(start) if start is not None else None
    manifest = {
        "preparation_status": "PASS", "publication_status": "NOT_PUBLISHED",
        "schema_version": SCHEMA_VERSION, "dataset_id": dataset_id,
        "source_time_basis": "Fixed AEST / UTC+10 (no daylight saving)", "payload_time_basis": "UTC",
        "source_files": provenance,
        "source_counts": {"configurations": len(stations), "hourly_prices": len(prices), "sessions": len(sessions), "meters": len(meters)},
        "full_dataset_price_events": sum(len(v) for v in price_changes.values()),
        "full_dataset_unchanged_price_rows_removed": len(prices) - sum(len(v) for v in price_changes.values()),
        "window": None if start is None else {
            "start_nem": start.isoformat(), "end_nem_exclusive": end.isoformat(),
            "start_utc": start_utc, "end_utc_exclusive": utc_string(end),
            "policy": "Sessions overlapping the window, including their real start/meter prefixes; price baseline before the earliest selected start and all subsequent changes. No fabricated ends.",
            "history_scope": "Selected sessions only; not all activity before window start. Warmup is not a complete historical replay.",
            "warmup_session_start_nem": warmup_start.isoformat(),
        },
        "selected_sessions": len(selected), "event_count": len(output),
        "event_counts": dict(Counter(e["event_type"] for e in output)),
        "warmup_event_count": sum(e["event_time"] < start_utc for e in output) if start_utc else 0,
        "first_event_time": output[0]["event_time"], "last_event_time": output[-1]["event_time"],
        "ordering": ["event_time", "price_update < meter < session_end < session_start", "event_id"],
        "minimum_publish_interval_seconds": 0.1,
        "minimum_spacing_duration_seconds": max(0, len(output) - 1) / 10,
        "stream_checks": replay_checks,
        "interface_status": "Task 2 contract 1.0; see docs/event_schema.md and docs/mqtt_topics.md. Publisher adds run_id.",
    }
    return output, manifest


def validate_stream(events: list[dict]) -> dict:
    """Replay the selected payloads to catch orphan meters and connector handoffs."""
    ids = set()
    active = {}
    latest_prices = {}
    previous_key = None
    completed = 0
    for index, row in enumerate(events, 1):
        require(row["sequence"] == index, "Non-contiguous sequence")
        require(row["event_id"] not in ids, "Duplicate event ID")
        ids.add(row["event_id"])
        key = event_key(row)
        require(previous_key is None or previous_key <= key, "Unordered event stream")
        previous_key = key
        cid, kind = row["charger_id"], row["event_type"]
        if kind == "price_update":
            price = row["price_per_kwh"]
            require(latest_prices.get(cid) != price, f"Unchanged consecutive price: {cid}")
            latest_prices[cid] = price
            continue
        connector = cid, row["connector_id"]
        if kind == "session_start":
            require(connector not in active, f"Connector still occupied before start: {connector}")
            require(cid in latest_prices and latest_prices[cid] == row["price_per_kwh"], f"Missing/wrong start price: {cid}")
            active[connector] = row["session_id"]
        else:
            require(active.get(connector) == row["session_id"], f"{kind} without its active session: {row['session_id']}")
            if kind == "session_end":
                del active[connector]
                completed += 1
    return {"unique_events": len(ids), "completed_sessions": completed, "active_sessions_at_end": len(active), "configuration_prices_at_end": len(latest_prices)}


def write_outputs(events: list[dict], manifest: dict, directory: Path, root: Path = ROOT) -> dict:
    directory = directory.resolve()
    protected = [root / "data/generated", root / "data/input", root / "data/processed", root / "data/source", root / "vendor", root / "database"]
    require(not any(directory.is_relative_to(p.resolve()) for p in protected), "Output directory must not overwrite upstream source or metadata directories")
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "events.json"
    temporary = directory / "events.json.tmp"
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("[\n")
        for index, payload in enumerate(events):
            if index:
                handle.write(",\n")
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        handle.write("\n]\n")
    temporary.replace(target)
    result = {**manifest, "events_file": "events.json", "events_sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "events_bytes": target.stat().st_size}
    temp_manifest = directory / "manifest.json.tmp"
    temp_manifest.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temp_manifest.replace(directory / "manifest.json")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", help="Inclusive source/NEM time, e.g. 2026-09-15T09:00:00")
    parser.add_argument("--end", help="Exclusive source/NEM time, e.g. 2026-09-15T13:00:00")
    parser.add_argument("--output-dir", type=Path, help="Default: data/events/full or a window-specific directory")
    args = parser.parse_args()
    try:
        start = market_time(args.start) if args.start else None
        end = market_time(args.end) if args.end else None
        events, manifest = prepare(ROOT, start, end)
        name = "full" if start is None else f"{start:%Y%m%dT%H%M%S}_{end:%Y%m%dT%H%M%S}"
        result = write_outputs(events, manifest, args.output_dir or ROOT / "data/events" / name)
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f"Event preparation failed: {exc}\n")
    print(json.dumps({key: result[key] for key in ("preparation_status", "publication_status", "event_count", "event_counts", "warmup_event_count", "stream_checks", "events_sha256", "events_bytes")}, indent=2))


if __name__ == "__main__":
    main()
