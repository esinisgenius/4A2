# Task 3 — MQTT Subscriber + Live Dashboard

Branch: `feature/task3-dashboard`. This is a standalone Task 3 implementation; Task 1/2 source files are unchanged.

## Setup

Python 3.12 recommended. Install `requirements-demo.txt` and additionally:

```bash
python -m pip install streamlit plotly pandas duckdb
```

Task 3 keeps a separate local **SQLite receive journal** at `database/task3_events.sqlite` for durable replay/deduplication. It is **not** the Task 4 DuckDB persistence deliverable; Task 4 must independently implement final event tables and metrics.

Start three terminals from repo root:

```bash
python src/local_broker.py
python src/subscriber.py --run-id team-demo-01
streamlit run dashboard/app.py
```

Wait for the subscriber's `SUBACK` message, then in a fourth terminal:

```bash
python src/publisher.py --events data/events/mqtt_demo/events.json --run-id team-demo-01
```

Select `team-demo-01` in the dashboard. For a fresh replay use a new run ID in subscriber, publisher, and dashboard. The MQTT broker is localhost-only unless configured otherwise. MQTT options: `--host`, `--port`, `--prefix`, `--tls`, `--ca-file`; env `MQTT_USERNAME`, `MQTT_PASSWORD`.

## Event semantics

- QoS 1 and no retain. Receipts are deduplicated using `(run_id,event_id)`.
- Topic station/charger IDs are checked against payload IDs; other runs are ignored.
- SQLite stores events transactionally. The dashboard projects unique records by *contiguous sequence*; a missing sequence pauses projection rather than silently showing inaccurate state.
- Latest prices are keyed by charger configuration (not physical site); map markers are physical stations.
- Charging remains active until `session_end` (unplug), even after `charge_end_time`.
- Meter charts plot the actual `event_time` and cumulative energy or instantaneous power.
- Historical metrics and state are scoped to the selected replay including any warmup, not the full source day. Sessions active at cutoff remain open.

## Limitations / Task 4 handoff

- This draft exposes current and historical metrics from the local Task 3 journal, **not yet the Task 4 DuckDB**. Integrate DuckDB queries once the Task 4 API/tables are available.
- The station inspector is a dropdown linked to markers by station ID; map-marker click-to-open details still needs an interaction bridge or compatible map component.
- The subscriber requires connectivity throughout playback. No retained messages: restart from a new run if state was lost.
- Tests: `python -m unittest tests/test_task3_state.py -v`. Full broker/publisher/dashboard end-to-end test remains to be performed on a machine with dependencies.
