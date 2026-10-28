"""Task 3 subscriber-side event journal and deterministic per-run projection.

SQLite is a local Task 3 checkpoint, NOT the Task 4 DuckDB deliverable.
Each event is committed before it can affect a dashboard projection.
"""
import json
import sqlite3
from pathlib import Path

TYPES = {"price_update", "session_start", "meter", "session_end"}
REQUIRED = {"schema_version", "dataset_id", "event_id", "run_id", "sequence",
            "event_type", "event_time", "station_id", "charger_id"}

def connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=20)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""CREATE TABLE IF NOT EXISTS received_events (
      run_id TEXT NOT NULL, event_id TEXT NOT NULL, sequence INTEGER NOT NULL,
      event_time TEXT NOT NULL, event_type TEXT NOT NULL, station_id TEXT NOT NULL,
      charger_id TEXT NOT NULL, payload TEXT NOT NULL,
      PRIMARY KEY (run_id,event_id), UNIQUE(run_id,sequence))""")
    conn.commit()
    return conn

def validate(event, expected_run=None):
    if not isinstance(event, dict) or not REQUIRED.issubset(event):
        raise ValueError("Missing required event fields")
    if event["schema_version"] != "1.0" or event["event_type"] not in TYPES:
        raise ValueError("Unsupported event contract")
    if expected_run is not None and event["run_id"] != expected_run:
        raise ValueError("Wrong run")
    for field in ("dataset_id", "event_id", "run_id", "event_time", "station_id", "charger_id"):
        if not isinstance(event[field], str) or not event[field]:
            raise ValueError("Invalid " + field)
    if type(event["sequence"]) is not int or event["sequence"] < 1:
        raise ValueError("Invalid sequence")
    if event["event_type"] != "price_update":
        if not isinstance(event.get("session_id"), str) or not event["session_id"]:
            raise ValueError("Missing session ID")
        if not isinstance(event.get("connector_id"), str) or not event["connector_id"].isdigit() or int(event["connector_id"]) < 1:
            raise ValueError("Invalid connector")
    required_by_type = {
        "price_update": ("price_per_kwh",),
        "session_start": ("price_per_kwh",),
        "meter": ("energy_kwh", "power_kw"),
        "session_end": ("energy_kwh", "cost_aud"),
    }
    for key in required_by_type[event["event_type"]]:
        if type(event.get(key)) not in (float, int):
            raise ValueError("Invalid " + key)
    return event

def insert(conn, event, run_id=None):
    validate(event, run_id)
    blob = json.dumps(event, sort_keys=True, separators=(",", ":"))
    try:
        with conn:
            conn.execute("INSERT INTO received_events VALUES (?,?,?,?,?,?,?,?)",
                         (event["run_id"], event["event_id"], event["sequence"],
                          event["event_time"], event["event_type"], event["station_id"],
                          event["charger_id"], blob))
        return True
    except sqlite3.IntegrityError:
        existing = conn.execute(
            "SELECT event_id,payload FROM received_events WHERE run_id=? AND (event_id=? OR sequence=?)",
            (event["run_id"], event["event_id"], event["sequence"])).fetchone()
        if existing == (event["event_id"], blob):
            return False
        raise ValueError("Conflicting event identity or sequence")

def load(conn, run_id):
    return [json.loads(row[0]) for row in conn.execute(
        "SELECT payload FROM received_events WHERE run_id=? ORDER BY sequence",
        (run_id,))]

def project(events):
    """Replay in sequence order. Out-of-order arrival is safe on next dashboard read.

    A gap is deliberately not applied; missing earlier events cannot be guessed.
    """
    prices, active, completed, meters, station_ids = {}, {}, {}, {}, set()
    applied = 0
    next_sequence = 1
    dataset_id = None
    for e in sorted(events, key=lambda x: x["sequence"]):
        if e["sequence"] != next_sequence:
            break
        next_sequence += 1
        applied += 1
        dataset_id = dataset_id or e["dataset_id"]
        if e["dataset_id"] != dataset_id:
            raise ValueError("Multiple datasets in one run")
        station_ids.add(e["station_id"])
        et, charger = e["event_type"], e["charger_id"]
        if et == "price_update":
            prices[charger] = e["price_per_kwh"]
        elif et == "session_start":
            sid = e["session_id"]
            if sid in active or sid in completed:
                raise ValueError("Duplicate session start")
            connector = (charger, e["connector_id"])
            if any((v["charger_id"], v["connector_id"]) == connector for v in active.values()):
                raise ValueError("Connector is already occupied")
            active[sid] = e
        elif et == "meter":
            sid = e["session_id"]
            if sid not in active:
                raise ValueError("Meter for inactive session")
            if meters.get(sid) and e["energy_kwh"] < meters[sid][-1]["energy_kwh"]:
                raise ValueError("Cumulative energy decreased")
            meters.setdefault(sid, []).append(e)
        else:
            sid = e["session_id"]
            if sid not in active:
                raise ValueError("End for inactive session")
            completed[sid] = e
            del active[sid]
    return {"prices": prices, "active": active, "completed": completed,
            "meters": meters, "station_ids": station_ids, "applied": applied,
            "total": len(events), "next_sequence": next_sequence,
            "dataset_id": dataset_id}
