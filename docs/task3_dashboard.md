# Task 3 — MQTT Subscriber + Live Dashboard

Branch: `feature/task3-dashboard`. This is a standalone Task 3 implementation; Task 1/2 source files are unchanged.

## Setup

Python 3.12 recommended. Install `requirements-demo.txt` and additionally:

```bash
python -m pip install -r requirements-task3.txt
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

## Marker interaction and run walkthrough

Click a blue/amber circle on the NSW map to open its full details; hovering shows only the station name. Set the matching run ID in the sidebar. Turn on the 5-second auto-refresh toggle to see MQTT meter curves grow, and turn it off temporarily if it interferes with manual map navigation. The initial map center and zoom target NSW. The short replay's 1,091 events are only a test window, not all 4,021 Task 1 sessions.

## Task 4 handoff (separate teammate)

Do not modify the Task 4 code or its DuckDB schema here. The Task 4 owner should persist all received MQTT messages in DuckDB, maintain run-scoped state and history, and offer an agreed query interface for current active sessions and completed-session statistics. Use common station/charger identifiers from P0, QoS 1, duplicate suppression on (run_id,event_id), and run-isolated session keys. Start both subscribers before the same publisher run and reconcile each receiver's distinct event counts against the publisher manifest. Task 3 currently reads its own SQLite journal for visualization, so displaying Task 3 metrics does NOT prove Task 4 DuckDB integration.

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
- Map markers use Folium popups. Hover shows a short station tooltip; clicking opens station name, address, charger-specific prices, operator, plug types, occupancy and original charger IDs. The station inspector remains available below the map.
- The subscriber requires connectivity throughout playback. No retained messages: restart from a new run if state was lost.
- Tests: `python -m unittest tests/test_task3_state.py -v`. Full broker/publisher/dashboard end-to-end test remains to be performed on a machine with dependencies.
