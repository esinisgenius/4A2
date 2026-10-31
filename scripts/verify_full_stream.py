"""Validate every prepared Task 2 event; optionally reconcile a finished MQTT/DuckDB run.

Run from repository root:
  python scripts/verify_full_stream.py
  python scripts/verify_full_stream.py --run-id ACTUAL_FULL_RUN_ID

Do not use --run-id while Streamlit holds the DuckDB write lock.
This command does not publish messages or modify the database.
"""
import argparse
from collections import Counter
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from publisher import load_events


def check(condition, detail):
    if not condition:
        raise AssertionError(detail)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, default=ROOT / "data/events/full/events.json")
    parser.add_argument("--manifest", type=Path, default=ROOT / "data/events/full/manifest.json")
    parser.add_argument("--run-id", help="Optional: compare fully MQTT-ingested run with prepared events")
    parser.add_argument("--database", type=Path, default=ROOT / "database/charger_analytics.duckdb")
    args = parser.parse_args()

    if not args.events.is_file():
        raise FileNotFoundError(f"Full event JSON missing: {args.events}. Run python src/prepare_events.py first.")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    check(manifest["preparation_status"] == "PASS", "Manifest preparation status not PASS")
    check(manifest["window"] is None, "Expected unwindowed full stream")
    events, digest = load_events(args.events)  # validates every event hash and whole sequence/semantics
    counts = Counter(e["event_type"] for e in events)
    check(digest == manifest["events_sha256"], "Full file SHA-256 differs from manifest")
    check(args.events.stat().st_size == manifest["events_bytes"], "File size differs from manifest")
    check(len(events) == manifest["event_count"], "Event count differs from manifest")
    check(dict(counts) == manifest["event_counts"], "Type counts differ from manifest")
    check(len({e["event_id"] for e in events}) == len(events), "Duplicate event ID")
    check(len({e["dataset_id"] for e in events}) == 1, "Mixed dataset IDs")
    check(events[0]["sequence"] == 1 and events[-1]["sequence"] == len(events),
          "Invalid sequence range")
    print("PASS prepared full event stream")
    print(json.dumps({"events": len(events), "counts": dict(counts), "sha256": digest,
                      "dataset_id": events[0]["dataset_id"]}, indent=2))

    if args.run_id:
        import duckdb
        if not args.database.is_file():
            raise FileNotFoundError(args.database)
        with duckdb.connect(str(args.database), read_only=True) as db:
            row = db.execute(
                "SELECT COUNT(*), MIN(sequence), MAX(sequence), COUNT(DISTINCT event_id), "
                "COUNT(DISTINCT dataset_id) FROM mqtt_events WHERE run_id=?", [args.run_id]
            ).fetchone()
            check(row == (len(events), 1, len(events), len(events), 1),
                  f"DuckDB completeness/uniqueness check failed: {row}")
            stored_counts = dict(db.execute(
                "SELECT event_type, COUNT(*) FROM mqtt_events "
                "WHERE run_id=? GROUP BY event_type", [args.run_id]
            ).fetchall())
            check(stored_counts == dict(counts), f"Event types mismatch: {stored_counts}")
            stored = db.execute(
                "SELECT payload FROM mqtt_events WHERE run_id=? ORDER BY sequence",
                [args.run_id],
            ).fetchall()
            for i, (record,) in enumerate(stored):
                payload = json.loads(record)
                check(payload.pop("run_id", None) == args.run_id,
                      f"Wrong run ID at event {i+1}")
                check(payload == events[i], f"MQTT/DuckDB payload mismatch at event {i+1}")
            check(db.execute(
                "SELECT COUNT(*) FROM charging_sessions WHERE run_id=? AND status='completed'",
                [args.run_id],
            ).fetchone()[0] == manifest["stream_checks"]["completed_sessions"],
                  "Completed-session state mismatch")
            check(db.execute(
                "SELECT COUNT(*) FROM active_connectors WHERE run_id=?", [args.run_id]
            ).fetchone()[0] == manifest["stream_checks"]["active_sessions_at_end"],
                  "Active-connector state mismatch")
        print(f"PASS MQTT/DuckDB run {args.run_id}: all {len(events)} stored payloads match exactly")
    else:
        print("MQTT/DuckDB full replay NOT verified (no --run-id supplied).")


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
